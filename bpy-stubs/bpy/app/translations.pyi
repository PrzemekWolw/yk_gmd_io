"""


Application Translations (bpy.app.translations)
***********************************************

This object contains some data/methods regarding internationalization in Blender, and allows every py script
to feature translations for its own UI messages.


Introduction
============

Warning: Most of this object should only be useful if you actually manipulate i18n stuff from Python.
If you are a regular add-on, you should only bother about :const:`contexts` member,
and the :func:`register`/:func:`unregister` functions! The :func:`pgettext` family of functions
should only be used in rare, specific cases (like e.g. complex "composited" UI strings...).

To add translations to your python script, you must define a dictionary formatted like that:
``{locale: {msg_key: msg_translation, ...}, ...}`` where:

* locale is either a lang iso code (e.g. ``fr``), a lang+country code (e.g. ``pt_BR``),
a lang+variant code (e.g. ``sr@latin``), or a full code (e.g. ``uz_UZ@cyrilic``).

* msg_key is a tuple (context, org message) - use, as much as possible, the predefined :const:`contexts`.

* msg_translation is the translated message in given language!

Then, call ``bpy.app.translations.register(__name__, your_dict)`` in your ``register()`` function, and
``bpy.app.translations.unregister(__name__)`` in your ``unregister()`` one.

The ``Manage UI translations`` add-on has several functions to help you collect strings to translate, and
generate the needed python code (the translation dictionary), as well as optional intermediary po files
if you want some... See
`How to Translate Blender <https://wiki.blender.org/wiki/Process/Translate_Blender>`_ and
`Using i18n in Blender Code <https://wiki.blender.org/wiki/Source/Interface/Internationalization>`_
for more info.


Module References
=================

.. code::

  import bpy

  # This block can be automatically generated by UI translations addon, which also handles conversion with PO format.
  # See also https://wiki.blender.org/wiki/Process/Translate_Blender#Translating_non-official_addons
  # It can (should) also be put in a different, specific py file.

  # ##### BEGIN AUTOGENERATED I18N SECTION #####
  # NOTE: You can safely move around this auto-generated block (with the begin/end markers!),
  #       and edit the translations by hand.
  #       Just carefully respect the format of the tuple!

  # Tuple of tuples ((msgctxt, msgid), (sources, gen_comments), (lang, translation, (is_fuzzy, comments)), ...)
  translations_tuple = (
      (("*", ""),
       ((), ()),
       ("fr_FR", "Project-Id-Version: Copy Settings 0.1.5 (r0)\nReport-Msgid-Bugs-To: \nPOT-Creation-Date: 2013-04-18 15:27:45.563524\nPO-Revision-Date: 2013-04-18 15:38+0100\nLast-Translator: Bastien Montagne <montagne29@wanadoo.fr>\nLanguage-Team: LANGUAGE <LL@li.org>\nLanguage: __POT__\nMIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n",
                 (False,
                  ("Blender's translation file (po format).",
                   "Copyright (C) 2013 The Blender Foundation.",
                   "This file is distributed under the same license as the Blender package.",
                   "FIRST AUTHOR <EMAIL@ADDRESS>, YEAR."))),
       ),
      (("Operator", "Render: Copy Settings"),
       (("bpy.types.SCENE_OT_render_copy_settings",),
        ()),
       ("fr_FR", "Rendu : copier réglages",
                 (False, ())),
       ),
      (("*", "Copy render settings from current scene to others"),
       (("bpy.types.SCENE_OT_render_copy_settings",),
        ()),
       ("fr_FR", "Copier les réglages de rendu depuis la scène courante vers d’autres",
                 (False, ())),
       ),
      # ... etc, all messages from your addon.
  )

  translations_dict = {}
  for msg in translations_tuple:
      key = msg[0]
      for lang, trans, (is_fuzzy, comments) in msg[2:]:
          if trans and not is_fuzzy:
              translations_dict.setdefault(lang, {})[key] = trans

  # ##### END AUTOGENERATED I18N SECTION #####

  # Define remaining addon (operators, UI...) here.


  def register():
     # Usual operator/UI/etc. registration...

      bpy.app.translations.register(__name__, translations_dict)


  def unregister():
      bpy.app.translations.unregister(__name__)

     # Usual operator/UI/etc. unregistration...

:data:`locale`

:data:`locales`

:data:`contexts_C_to_py`

:data:`contexts`

:func:`locale_explode`

:func:`pgettext`

:func:`pgettext_data`

:func:`pgettext_iface`

:func:`pgettext_tip`

:func:`register`

:func:`unregister`

"""

import typing

locale: typing.Any = ...

"""

The actual locale currently in use (will always return a void string when Blender is built without internationalization support).

"""

locales: typing.Any = ...

"""

All locales currently known by Blender (i.e. available as translations).

"""

contexts_C_to_py: typing.Any = ...

"""

A readonly dict mapping contexts' C-identifiers to their py-identifiers.

"""

contexts: typing.Any = ...

"""

Constant value bpy.app.translations.contexts(default_real=None, default='*', operator_default='Operator', ui_events_keymaps='UI_Events_KeyMaps', plural='Plural', id_action='Action', id_armature='Armature', id_brush='Brush', id_camera='Camera', id_cachefile='CacheFile', id_collection='Collection', id_curve='Curve', id_fs_linestyle='FreestyleLineStyle', id_gpencil='GPencil', id_hair='Hair', id_id='ID', id_image='Image', id_shapekey='Key', id_light='Light', id_library='Library', id_lattice='Lattice', id_mask='Mask', id_material='Material', id_metaball='Metaball', id_mesh='Mesh', id_movieclip='MovieClip', id_nodetree='NodeTree', id_object='Object', id_paintcurve='PaintCurve', id_palette='Palette', id_particlesettings='ParticleSettings', id_pointcloud='PointCloud', id_lightprobe='LightProbe', id_scene='Scene', id_screen='Screen', id_sequence='Sequence', id_simulation='Simulation', id_speaker='Speaker', id_sound='Sound', id_texture='Texture', id_text='Text', id_vfont='VFont', id_volume='Volume', id_world='World', id_workspace='WorkSpace', id_windowmanager='WindowManager')

"""

def locale_explode(self, locale: typing.Any) -> None:

  """

  Return all components and their combinations  of the given ISO locale string.

  >>> bpy.app.translations.locale_explode("sr_RS@latin")
  ("sr", "RS", "latin", "sr_RS", "sr@latin")

  For non-complete locales, missing elements will be None.

  """

  ...

def pgettext(self, msgid: str, msgctxt: str = None) -> None:

  """

  Try to translate the given msgid (with optional msgctxt).

  Note: The ``(msgid, msgctxt)`` parameters order has been switched compared to gettext function, to allow
single-parameter calls (context then defaults to BLT_I18NCONTEXT_DEFAULT).

  Note: You should really rarely need to use this function in regular addon code, as all translation should be
handled by Blender internal code. The only exception are string containing formatting (like "File: %r"),
but you should rather use :func:`pgettext_iface`/:func:`pgettext_tip` in those cases!

  Note: Does nothing when Blender is built without internationalization support (hence always returns ``msgid``).

  """

  ...

def pgettext_data(self, msgid: str, msgctxt: str = None) -> None:

  """

  Try to translate the given msgid (with optional msgctxt), if new data name's translation is enabled.

  Note: See :func:`pgettext` notes.

  """

  ...

def pgettext_iface(self, msgid: str, msgctxt: str = None) -> None:

  """

  Try to translate the given msgid (with optional msgctxt), if labels' translation is enabled.

  Note: See :func:`pgettext` notes.

  """

  ...

def pgettext_tip(self, msgid: str, msgctxt: str = None) -> None:

  """

  Try to translate the given msgid (with optional msgctxt), if tooltips' translation is enabled.

  Note: See :func:`pgettext` notes.

  """

  ...

def register(self, module_name: str, translations_dict: typing.Dict[str, typing.Any]) -> None:

  """

  Registers an addon's UI translations.

  Note: Does nothing when Blender is built without internationalization support.

  """

  ...

def unregister(self, module_name: str) -> None:

  """

  Unregisters an addon's UI translations.

  Note: Does nothing when Blender is built without internationalization support.

  """

  ...
