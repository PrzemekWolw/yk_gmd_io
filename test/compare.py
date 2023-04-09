import argparse
import itertools
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Callable, TypeVar, Tuple, cast, Iterable, Set, DefaultDict, Optional, Dict

from mathutils import Vector
from yk_gmd_blender.blender.importer.mesh.vertex_fusion import vertex_fusion, make_bone_indices_consistent
from yk_gmd_blender.yk_gmd.v2.abstract.gmd_mesh import GMDMesh, GMDSkinnedMesh
from yk_gmd_blender.yk_gmd.v2.abstract.gmd_shader import GMDVertexBuffer_Generic, GMDVertexBuffer_Skinned
from yk_gmd_blender.yk_gmd.v2.abstract.nodes.gmd_bone import GMDBone
from yk_gmd_blender.yk_gmd.v2.abstract.nodes.gmd_node import GMDNode
from yk_gmd_blender.yk_gmd.v2.abstract.nodes.gmd_object import GMDSkinnedObject, GMDUnskinnedObject
from yk_gmd_blender.yk_gmd.v2.converters.common.to_abstract import FileImportMode, VertexImportMode
from yk_gmd_blender.yk_gmd.v2.errors.error_reporter import LenientErrorReporter, ErrorReporter
from yk_gmd_blender.yk_gmd.v2.io import read_gmd_structures, read_abstract_scene_from_filedata_object
from yk_gmd_blender.yk_gmd.v2.structure.common.node import NodeType
from yk_gmd_blender.yk_gmd.v2.structure.endianness import check_are_vertices_big_endian, check_is_file_big_endian

T = TypeVar('T')


def sort_src_dest_lists(src: Iterable[T], dst: Iterable[T], key: Callable[[T], str]) -> Tuple[List[T], List[T]]:
    sorted_src: List[T] = [n for n in src]
    sorted_src.sort(key=key)
    sorted_dst: List[T] = [n for n in dst]
    sorted_dst.sort(key=key)

    return sorted_src, sorted_dst


@dataclass(frozen=True)
class VertApproxData:
    normal: Optional[Tuple]
    tangent: Optional[Tuple]

    @staticmethod
    def new(normal: Optional[Vector], tangent: Optional[Vector]):
        return VertApproxData(
            normal=tuple(round(x, 2) for x in normal.resized(4)) if normal is not None else None,
            tangent=tuple(round(x, 2) for x in tangent.resized(4)) if tangent is not None else None
        )

    def approx_eq(self, other: 'VertApproxData') -> bool:
        t = 0.9  # equality threshold
        if self.normal is None:
            if other.normal is not None:
                return False
        else:
            if other.normal is None or Vector(self.normal).dot(Vector(other.normal)) < t:
                return False

        # if self.tangent is None:
        #     if other.tangent is not None:
        #         return False
        # else:
        #     if other.tangent is None or Vector(self.tangent).dot(Vector(other.tangent)) < t:
        #         return False

        return True

    def __lt__(self, other) -> bool:
        return (self.normal, self.tangent) < (other.normal, other.tangent)

    def __gt__(self, other) -> bool:
        return (self.normal, self.tangent) > (other.normal, other.tangent)


class VertSet:
    """
    Class for storing sets of vertex data, split into "exact" and "approximate" data.
    When computing the difference of two sets, first compares exact parts then
    sees if the approximate parts are close enough.
    """
    verts: DefaultDict[Tuple, Set[VertApproxData]]
    len: int

    def __init__(self):
        self.verts = defaultdict(lambda: set())
        self.len = 0

    def add(self, vert_exact: Tuple, vert_approx: VertApproxData):
        self.verts[vert_exact].add(vert_approx)
        self.len += 1

    def exact_difference(self, other: 'VertSet') -> Set[Tuple]:
        """
        Returns the difference in exact data of two vert-sets as a set
        (i.e. all exact data elements that are in this set but not the others)

        :param other: The other set
        :return: Set of vert_exact tuples not found in the other set
        """
        return set(self.verts.keys()).difference(other.verts.keys())

    def difference(self, other: 'VertSet') -> Dict[Tuple, Tuple[VertApproxData]]:
        """
        Return the difference of two vert-sets as a set.
        (i.e. all elements that are in this set but not the others.)

        Returns a set of tuples: (vert_exact, vert_approx) not found in the other set,
        i.e. for which there does not exist a vert_approx_alt in other.verts[vert_exact]
        where vert_approx.approx_eq(vert_approx_alt)

        :param other: The other set
        :return: Set of (vert_exact, vert_approx) tuples not found in the other set
        """

        verts: Dict[Tuple, Tuple[VertApproxData]] = {}

        key_set = set(self.verts.keys())

        # 1. Find vert_exacts that don't match
        for vert_exact in key_set.difference(other.verts.keys()):
            # foreach vert_exact that doesn't exist in the other verts
            # add all (vert_exact, vert_approx) pairs to the set
            verts[vert_exact] = tuple(v_a for v_a in self.verts[vert_exact])

        # 2. Find vert_approx that don't match within vert_exacts that do match
        for vert_exact in key_set.intersection(other.verts.keys()):
            # foreach vert_exact that is in both sets
            # check the vert_approx lists
            self_approx = self.verts[vert_exact]
            other_approx = other.verts[vert_exact]
            # O(n^2), but there shouldn't be many items in either list
            differing_va = tuple(
                v_a
                for v_a in self_approx
                if not any(v_a.approx_eq(v_a_alt) for v_a_alt in other_approx)
            )
            if len(differing_va) > 0:
                verts[vert_exact] = differing_va

        return verts

    def __len__(self):
        return self.len


class FusedVertVoxelSet:
    """
    Class for storing sets of vertex data grouped into 3D voxels
    """
    # Mapping of (voxel centre) -> [vert_index for each vert in voxel]
    voxels: DefaultDict[Tuple[int, int, int], List[int]]
    # List of (exact pos, exact normal, boneweights)
    verts: List[Tuple[Vector, Vector, Tuple]]
    voxel_size: float

    def __init__(self, voxel_size: float = 0.0001):
        self.voxels = defaultdict(list)
        self.voxel_size = voxel_size
        self.verts = []

    def add(self, exact_pos: Vector, exact_norm: Vector, rounded_bw: Tuple):
        voxel = (
            int(exact_pos.x / self.voxel_size), int(exact_pos.y / self.voxel_size), int(exact_pos.z / self.voxel_size))
        self.voxels[voxel].append(len(self.verts))
        self.verts.append((exact_pos, exact_norm, rounded_bw))

    def check_one_to_one(self, other: 'FusedVertVoxelSet', pos_epsilon: float = 0.00001):
        # AAAH
        # LJ kaito: src: 5483 post-fusion, dst: 6321 post-fusion
        # In LJ kaito, this manifests as creating multiple vertices on the same point that no longer fuse
        # This is a problem, because it means those fusions don't go to the same normals anymore
        # => we are targeting the case where a single src fused vertex maps to multiple dst fused vertices
        # => i.e. the position and boneweights are the same (the exact_pos is close, and the rounded data is the same)
        # Algorithm
        # for every vertex in src
        #     check dst for a list of fused vertices within (e=0.001) range
        #     if there isn't any, that's bad - the vertex has disappeared
        #     also check src for a list of vertices within (e=0.001) range
        #     if len(src) > len(dst), that's fine - assume more verts have been fused
        #     if len(src) == len(dst), that's fine - assume all verts are the same
        #     if len(src) < len(dst), that's bad - the vertices have been split in a way that breaks re-fusion

        assert self.voxel_size == other.voxel_size
        assert self.voxel_size > pos_epsilon

        has_no_equiv_in_other: List[Tuple[Vector, Vector, Tuple]] = []
        was_unfused_in_other = []

        counted_other_verts: Set[int] = set()
        pos_epsilon_sqr = pos_epsilon ** 2

        for voxel_key, verts in self.voxels.items():
            other_search_space = [
                (other_i, other.verts[other_i])
                for x in (voxel_key[0] - 1, voxel_key[0], voxel_key[0] + 1, voxel_key[0] + 2)
                for y in (voxel_key[1] - 1, voxel_key[1], voxel_key[1] + 1, voxel_key[1] + 2)
                for z in (voxel_key[2] - 1, voxel_key[2], voxel_key[2] + 1, voxel_key[2] + 2)
                for other_i in other.voxels[(x, y, z)]
            ]
            self_search_space = [
                (self_i, self.verts[self_i])
                for x in (voxel_key[0] - 1, voxel_key[0], voxel_key[0] + 1, voxel_key[0] + 2)
                for y in (voxel_key[1] - 1, voxel_key[1], voxel_key[1] + 1, voxel_key[1] + 2)
                for z in (voxel_key[2] - 1, voxel_key[2], voxel_key[2] + 1, voxel_key[2] + 2)
                if (x, y, z) in self.voxels
                for self_i in self.voxels[(x, y, z)]
            ]

            for self_vert in verts:
                self_v_pos, self_v_norm, self_v_rounded_bw = self.verts[self_vert]

                potential_other_verts = [
                    (other_fused_idx, tuple(round(n, 3) for n in other_norm) if other_norm else None, other_pos)
                    for other_fused_idx, (other_pos, other_norm, other_rounded_bw) in other_search_space
                    if other_rounded_bw == self_v_rounded_bw and
                       (self_v_pos - other_pos).length_squared < pos_epsilon_sqr
                ]
                counted_other_verts.update(i for (i, _, _) in potential_other_verts)

                potential_self_verts = [
                    (other_fused_idx, tuple(round(n, 3) for n in other_norm) if other_norm else None, other_pos)
                    for other_fused_idx, (other_pos, other_norm, other_rounded_bw) in self_search_space
                    if other_rounded_bw == self_v_rounded_bw and
                       (self_v_pos - other_pos).length_squared < pos_epsilon_sqr
                ]

                if len(potential_other_verts) == 0:
                    has_no_equiv_in_other.append((self_v_pos, self_v_norm, self_v_rounded_bw))
                elif len(potential_other_verts) > len(potential_self_verts):
                    was_unfused_in_other.append(
                        (self_v_pos, self_v_rounded_bw, potential_self_verts, potential_other_verts))

        other_vs_with_no_equiv_in_self = [
            other.verts[other_i]
            for other_i in range(len(other))
            if other_i not in counted_other_verts
        ]

        return has_no_equiv_in_other, was_unfused_in_other, other_vs_with_no_equiv_in_self

    def __len__(self):
        return len(self.verts)


def get_unique_verts(ms: List[GMDMesh]) -> VertSet:
    nul_item = (0,)
    all_verts = VertSet()
    for gmd_mesh in ms:
        buf = gmd_mesh.vertices_data
        for i in set(gmd_mesh.triangle_strip_noreset_indices):
            all_verts.add(
                (
                    tuple(round(x, 2) for x in buf.pos[i]),
                    round(buf.normal[i].w, 4) if buf.normal else nul_item,
                    round(buf.tangent[i].w, 4) if buf.tangent else nul_item,
                    tuple(round(x, 2) for x in buf.col0[i]) if buf.col0 else nul_item,
                    tuple(round(x, 2) for x in buf.col1[i]) if buf.col1 else nul_item,
                    tuple(round(x, 2) for x in buf.unk[i]) if buf.unk else nul_item,
                    tuple(round(x, 2) for uv in buf.uvs for x in uv[i]),
                    "b",
                    tuple(round(x, 1) for x in buf.bone_data[i]) if buf.bone_data else nul_item,
                    "w",
                    tuple(round(x, 2) for x in buf.weight_data[i]) if buf.weight_data else nul_item,
                ),
                VertApproxData.new(
                    normal=buf.normal[i] if buf.normal else None,
                    tangent=buf.tangent[i] if buf.tangent else None
                )
            )
    return all_verts


def get_unique_skinned_verts(ms: List[GMDSkinnedMesh]) -> VertSet:
    nul_item = (0,)
    all_verts = VertSet()
    for gmd_mesh in ms:
        buf = gmd_mesh.vertices_data
        for i in set(gmd_mesh.triangle_strip_noreset_indices):
            assert buf.bone_data and buf.weight_data
            all_verts.add(
                (
                    tuple(round(x, 2) for x in buf.pos[i]),
                    round(buf.normal[i].w, 4) if buf.normal else nul_item,
                    round(buf.tangent[i].w, 4) if buf.tangent else nul_item,
                    tuple(round(x, 2) for x in buf.col0[i]) if buf.col0 else nul_item,
                    tuple(round(x, 2) for x in buf.col1[i]) if buf.col1 else nul_item,
                    tuple(round(x, 2) for x in buf.unk[i]) if buf.unk else nul_item,
                    tuple(round(x, 2) for uv in buf.uvs for x in uv[i]),
                    "bw",
                    tuple(
                        (gmd_mesh.relevant_bones[int(b)].name, round(w, 3))
                        for (b, w) in zip(buf.bone_data[i], buf.weight_data[i])
                        if w > 0
                    ) if buf.bone_data and buf.weight_data else nul_item,
                ),
                VertApproxData.new(
                    normal=buf.normal[i] if buf.normal else None,
                    tangent=buf.tangent[i] if buf.tangent else None
                )
            )
    return all_verts


def compare_same_layout_mesh_vertex_fusions(skinned: bool, src: List[GMDMesh], dst: List[GMDMesh], error: ErrorReporter,
                                            context: str) -> bool:
    # The point of this test is to check that reexporting data didn't unfuse some vertices
    # i.e. we want to make sure every fused vertex in src has *exactly* one equivalent fused vertex in dst

    nul_item = (0,)

    # Create a set of fused vertices for src and dst
    # Use a Voxel set, where the vertices are grouped by position, to make finding nearby vertices for fusion less complex
    def find_fusion_output_vs(ms: List[GMDMesh]) -> FusedVertVoxelSet:
        unfused_vs: List[GMDVertexBuffer_Generic]
        if skinned:
            relevant_bones, unfused_vs = make_bone_indices_consistent(cast(List[GMDSkinnedMesh], ms))
        else:
            unfused_vs = [m.vertices_data for m in ms]
        fused_idx_to_buf_idx, _, _ = vertex_fusion([m.triangle_indices for m in ms], unfused_vs)

        all_verts = FusedVertVoxelSet()
        if skinned:
            for (fused_i, buf_idxs) in enumerate(fused_idx_to_buf_idx):
                buf_idx, i = buf_idxs[0]
                buf = cast(GMDVertexBuffer_Skinned, unfused_vs[buf_idx])

                exact_pos = buf.pos[i]
                rounded_bw = (
                    tuple(
                        (relevant_bones[int(bw.bone)].name, round(bw.weight, 4))
                        for bw in buf.bone_weights[i]
                        if bw.weight > 0
                    ) if buf.bone_weights else nul_item,
                )
                norm = buf.normal[i].xyz if buf.normal else None
                all_verts.add(exact_pos, norm, rounded_bw)
        else:
            for (fused_i, buf_idxs) in enumerate(fused_idx_to_buf_idx):
                buf_idx, i = buf_idxs[0]
                buf = unfused_vs[buf_idx]

                exact_pos = buf.pos[i]
                rounded_bw = (
                    tuple(round(x, 4) for x in buf.bone_data[i]) if buf.bone_data else nul_item,
                    tuple(round(x, 4) for x in buf.weight_data[i]) if buf.weight_data else nul_item,
                )
                norm = buf.normal[i].xyz if buf.normal else None
                all_verts.add(exact_pos, norm, rounded_bw)

        return all_verts

    src_fused_vs = find_fusion_output_vs(src)
    src_n_fused_vs = len(src_fused_vs)
    dst_fused_vs = find_fusion_output_vs(dst)
    dst_n_fused_vs = len(dst_fused_vs)

    # Compare the src fused set with the dst fused set
    (src_vs_with_no_equiv, src_vs_unfused_in_dst, dst_vs_with_no_equiv_in_src) = \
        src_fused_vs.check_one_to_one(dst_fused_vs)
    if src_vs_with_no_equiv or src_vs_unfused_in_dst or dst_vs_with_no_equiv_in_src:
        src_with_no_equiv_str = '\n\t'.join(str(x) for x in itertools.islice(sorted(src_vs_with_no_equiv), 5))
        n_in_src_unfused = len(set(i for _, _, ss, _ in src_vs_unfused_in_dst for i, _, _ in ss))
        n_in_dst_unfused = len(set(i for _, _, _, ds in src_vs_unfused_in_dst for i, _, _ in ds))
        src_unfused_str = '\n\t'.join(
            str(x) for x in
            itertools.islice(sorted([v for v in src_vs_unfused_in_dst]), 5))
        dst_with_no_equiv_str = '\n\t'.join(str(x) for x in itertools.islice(sorted(dst_vs_with_no_equiv_in_src), 5))
        error.fatal(
            f"{context}src ({src_n_fused_vs} fused vs) and dst ({dst_n_fused_vs} fused vs) (delta {dst_n_fused_vs - src_n_fused_vs}) don't match\n\t"
            f"found {len(src_vs_with_no_equiv)} vs in src with no equiv in dst:\n\t"
            f"{src_with_no_equiv_str}...\n\t"
            f"found {len(src_vs_unfused_in_dst)} groups of src vs with multiple possible equivalents.\n\t"
            f"{n_in_dst_unfused} dst - {n_in_src_unfused} src = {n_in_dst_unfused - n_in_src_unfused} delta\n\t"
            f"{src_unfused_str}...\n\t"
            f"found {len(dst_vs_with_no_equiv_in_src)} vs in dst with no equiv in src:\n\t"
            f"{dst_with_no_equiv_str}...\n\t"
        )
        return False
    if src_n_fused_vs != dst_n_fused_vs:
        error.recoverable(
            f"{context}src ({src_n_fused_vs} fused vs) and dst ({dst_n_fused_vs} fused vs) don't match, but we don't know why\n\t")
    return True


def compare_same_layout_meshes(skinned: bool, src: List[GMDMesh], dst: List[GMDMesh], error: ErrorReporter,
                               context: str) -> bool:
    if skinned:
        src_vertices = get_unique_skinned_verts(src)
        dst_vertices = get_unique_skinned_verts(dst)
    else:
        src_vertices = get_unique_verts(src)
        dst_vertices = get_unique_verts(dst)

    src_but_not_dst_exact = src_vertices.exact_difference(dst_vertices)
    dst_but_not_src_exact = dst_vertices.exact_difference(src_vertices)

    if src_but_not_dst_exact or dst_but_not_src_exact:
        src_but_not_dst_str = '\n\t'.join(str(x) for x in itertools.islice(sorted(src_but_not_dst_exact), 5))
        dst_but_not_src_str = '\n\t'.join(str(x) for x in itertools.islice(sorted(dst_but_not_src_exact), 5))
        error.fatal(
            f"{context}src ({len(src_vertices)} unique verts) and dst ({len(dst_vertices)} unique verts) exact data differs\n\t"
            f"src meshes have {len(src_but_not_dst_exact)} vertices missing in dst:\n\t"
            f"{src_but_not_dst_str}...\n\t"
            f"dst meshes have {len(dst_but_not_src_exact)} vertices not in src:\n\t"
            f"{dst_but_not_src_str}...")
        return False

    src_but_not_dst = src_vertices.difference(dst_vertices)
    dst_but_not_src = dst_vertices.difference(src_vertices)

    if src_but_not_dst or dst_but_not_src:
        src_but_not_dst_str = '\n\t'.join(
            f"{str(k)}:\n\t\t" + '\n\t\t'.join(str(x) for x in src_but_not_dst[k])
            for k in itertools.islice(sorted(src_but_not_dst.keys()), 5)
        )
        dst_but_not_src_str = '\n\t'.join(
            f"{str(k)}:\n\t\t" + '\n\t\t'.join(str(x) for x in dst_but_not_src[k])
            for k in itertools.islice(sorted(dst_but_not_src.keys()), 5)
        )
        error.recoverable(
            f"{context}src ({len(src_vertices)} unique verts) and dst ({len(dst_vertices)} unique verts) APPROX data differs\n\t"
            f"src meshes have {len(src_but_not_dst)} vertices missing in dst:\n\t"
            f"{src_but_not_dst_str}...\n\t"
            f"dst meshes have {len(dst_but_not_src)} vertices not in src:\n\t"
            f"{dst_but_not_src_str}...")
        return False
    return True


def compare_single_node_pair(skinned: bool, vertices: bool, src: GMDNode, dst: GMDNode, error: ErrorReporter,
                             context: str):
    from math import fabs

    def compare_field(f: str):
        if getattr(src, f) != getattr(dst, f):
            error.fatal(f"{context}: field '{f}' differs:\nsrc:\n\t{getattr(src, f)}\ndst:\n\t{getattr(dst, f)}")

    def compare_vec_field(f: str):
        src_f = tuple(round(x, 3) for x in getattr(src, f))
        dst_f = tuple(round(x, 3) for x in getattr(dst, f))
        if src_f != dst_f:
            if sum(fabs(s - r) for (s, r) in zip(src_f, dst_f)) > 0.05:
                error.fatal(f"{context}: vector '{f}'' differs:\nsrc:\n\t{src_f}\ndst:\n\t{dst_f}")
            else:
                error.recoverable(f"{context}: vector '{f}' differs slightly:\nsrc:\n\t{src_f}\ndst:\n\t{dst_f}")

    def compare_mat_field(f: str):
        src_f = tuple(tuple(round(x, 3) for x in v) for v in getattr(src, f))
        dst_f = tuple(tuple(round(x, 3) for x in v) for v in getattr(dst, f))
        if src_f != dst_f:
            src_floats = tuple(x for v in src_f for x in v)
            dst_floats = tuple(x for v in dst_f for x in v)
            if sum(fabs(s - r) for (s, r) in zip(src_floats, dst_floats)) > 0.05:
                error.fatal(f"{context}: matrix '{f}' differs:\nsrc:\n\t{src_f}\ndst:\n\t{dst_f}")
            else:
                error.recoverable(f"{context}: matrix '{f}' differs slightly:\nsrc:\n\t{src_f}\ndst:\n\t{dst_f}")

    # Compare subclass-agnostic, hierarchy-agnostic values
    compare_field("node_type")
    compare_vec_field("pos")
    compare_vec_field("rot")
    compare_vec_field("scale")
    compare_vec_field("world_pos")
    compare_vec_field("anim_axis")
    compare_field("flags")

    if not isinstance(src, GMDSkinnedObject):
        compare_mat_field("matrix")

    if src.node_type == dst.node_type:
        if src.node_type == NodeType.MatrixTransform:
            assert isinstance(src, GMDBone)
            pass  # Nothing more to check
        else:
            # Compare meshes
            assert isinstance(src, (GMDSkinnedObject, GMDUnskinnedObject))
            assert isinstance(dst, (GMDSkinnedObject, GMDUnskinnedObject))

            src_attrs = set(str(m.attribute_set) for m in cast(List[GMDMesh], src.mesh_list))
            dst_attrs = set(str(m.attribute_set) for m in cast(List[GMDMesh], dst.mesh_list))

            # Generate sorted attribute set lists to compare them
            # If there are different materials, there's a problem
            sorted_attrs_src, sorted_attrs_dst = sort_src_dest_lists(
                src_attrs,
                dst_attrs,
                key=lambda x: x
            )

            if sorted_attrs_src != sorted_attrs_dst:
                error.fatal(
                    f"{context} has different sets of attribute sets:\nsrc:\n\t{sorted_attrs_src}\ndst:{sorted_attrs_dst}\n\t")

            if vertices:
                # For each unique attribute set
                # compare the vertices in the sets of meshes that use it
                unique_attr_sets = []
                for m in src.mesh_list:
                    if m.attribute_set not in unique_attr_sets:
                        unique_attr_sets.append(m.attribute_set)

                identical = True
                for attr in unique_attr_sets:
                    src_ms = [m for m in src.mesh_list if m.attribute_set == attr]
                    dst_ms = [m for m in dst.mesh_list if m.attribute_set == attr]

                    if not compare_same_layout_meshes(
                            skinned,
                            src_ms,
                            dst_ms,
                            error, f"{context}attr set {attr.texture_diffuse} "
                    ):
                        identical = False
                if not compare_same_layout_mesh_vertex_fusions(skinned, src.mesh_list, dst.mesh_list, error, context):
                    identical = False
                if identical:
                    error.info(f"{context} meshes are functionally identical")


def recursive_compare_node_lists(skinned: bool, vertices: bool, src: List[GMDNode], dst: List[GMDNode],
                                 error: ErrorReporter, context: str):
    src_names_unordered = set(n.name for n in src)
    dst_names_unordered = set(n.name for n in dst)
    if src_names_unordered != dst_names_unordered:
        error.fatal(
            f"{context} has different sets of children:\nsrc:\n\t{src_names_unordered}\ndst:{dst_names_unordered}\n\t")

    src_names = [n.name for n in src]
    dst_names = [n.name for n in dst]
    if src_names != dst_names:
        error.fatal(f"{context} children in different order:\nsrc:\n\t{src_names}\ndst:{dst_names}\n\t")

    for child_src, child_dst in zip(src, dst):
        child_context = f"{context}{child_src.name} > "
        compare_single_node_pair(skinned, vertices, child_src, child_dst, error, child_context)
        recursive_compare_node_lists(skinned, vertices, child_src.children, child_dst.children, error, child_context)


def compare_files(file_src: Path, file_dst: Path, skinned: bool, vertices: bool, error: ErrorReporter):
    # Load and compare basic information - GMD version, headers
    version_props_src, header_src, file_data_src = read_gmd_structures(file_src, error)
    version_props_dst, header_dst, file_data_dst = read_gmd_structures(file_dst, error)

    if version_props_src != version_props_dst:
        error.fatal(f"Version props mismatch\nsrc:\n\t{version_props_src}\ndst:\n\t{version_props_dst}")

    def compare_header_field(f: str):
        if getattr(header_src, f) != getattr(header_dst, f):
            error.recoverable(
                f"header: field {f} differs:\nsrc:\n\t{getattr(header_src, f)}\ndst:\n\t{getattr(header_dst, f)}")

    compare_header_field("magic")
    # Compare endianness
    if check_are_vertices_big_endian(header_src.vertex_endian_check) != \
            check_are_vertices_big_endian(header_dst.vertex_endian_check):
        error.recoverable(
            f"header: vertex endian differs:\nsrc:\n\t"
            f"{header_src.vertex_endian_check} {check_are_vertices_big_endian(header_src.vertex_endian_check)}\n"
            f"dst:\n\t{header_dst.vertex_endian_check} {check_are_vertices_big_endian(header_dst.vertex_endian_check)}")
    if check_is_file_big_endian(header_src.file_endian_check) != \
            check_is_file_big_endian(header_dst.file_endian_check):
        error.recoverable(
            f"header: file endian differs:\nsrc:\n\t"
            f"{header_src.file_endian_check} {check_is_file_big_endian(header_src.file_endian_check)}\n"
            f"dst:\n\t{header_dst.file_endian_check} {check_is_file_big_endian(header_dst.file_endian_check)}")
    compare_header_field("version_combined")
    compare_header_field("name")
    compare_header_field("padding")

    # Technically YK1-specific?
    compare_header_field("overall_bounds")
    compare_header_field("flags")

    # Load and compare scene hierarchies
    import_mode = VertexImportMode.IMPORT_VERTICES if vertices else VertexImportMode.NO_VERTICES

    scene_src = read_abstract_scene_from_filedata_object(version_props_src,
                                                         FileImportMode.SKINNED if skinned else FileImportMode.UNSKINNED,
                                                         import_mode,
                                                         file_data_src, error)
    scene_dst = read_abstract_scene_from_filedata_object(version_props_dst,
                                                         FileImportMode.SKINNED if skinned else FileImportMode.UNSKINNED,
                                                         import_mode,
                                                         file_data_dst, error)

    recursive_compare_node_lists(skinned, vertices, scene_src.overall_hierarchy.roots,
                                 scene_dst.overall_hierarchy.roots, error, "")


if __name__ == '__main__':
    parser = argparse.ArgumentParser("GMD Comparer")

    parser.add_argument("file_src", type=Path)
    parser.add_argument("file_dst", type=Path)
    parser.add_argument("--skinned", action="store_true")
    parser.add_argument("--vertices", action="store_true")

    args = parser.parse_args()

    error = LenientErrorReporter(allowed_categories=set())

    compare_files(args.file_src, args.file_dst, args.skinned, args.vertices, error)