bl_info = {
	"name": "VF Auto Save Render",
	"author": "John Einselen - Vectorform LLC, based on work by tstscr(florianfelix)",
	"version": (0, 4),
	"blender": (2, 80, 0),
	"location": "Rendertab > Output Panel > Subpanel",
	"description": "Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
	# "description": "Automatically saves a numbered or dated image after every render is completed or canceled",
	"warning": "inexperienced developer, use at your own risk",
	"wiki_url": "http://wiki.blender.org/index.php/Extensions:2.6/Py/Scripts/Render/Auto_Save",
	"category": "Render"}

# Based on the following resources:
# https://gist.github.com/egetun/1224aa600a32bd38fa771df463796977
# https://github.com/patrickhill/blender-datestamper/blob/master/render_auto_save_with_datestamp.py
# https://gist.github.com/robertguetzkow/8dacd4b565538d657b72efcaf0afe07e
# https://blender.stackexchange.com/questions/6842/how-to-get-the-directory-of-open-blend-file-from-python

import os
import datetime
import bpy
from bpy.app.handlers import persistent
from re import findall, search
from pathlib import Path

IMAGE_FORMATS = (
	'BMP',
	'IRIS',
	'PNG',
	'JPEG',
	'JPEG2000',
	'TARGA',
	'TARGA_RAW',
	'CINEON',
	'DPX',
	'OPEN_EXR_MULTILAYER',
	'OPEN_EXR',
	'HDR',
	'TIFF')
IMAGE_EXTENSIONS = (
	'bmp',
	'rgb',
	'png',
	'jpg',
	'jp2',
	'tga',
	'cin',
	'dpx',
	'exr',
	'hdr',
	'tif'
)

@persistent
def auto_save_render(scene):
	if not bpy.context.scene.auto_save_render_settings.enable_auto_save_render or not bpy.data.filepath:
		return
	rndr = scene.render
	original_format = rndr.image_settings.file_format
	original_colormode = rndr.image_settings.color_mode
	original_colordepth = rndr.image_settings.color_depth

	if bpy.context.scene.auto_save_render_settings.auto_save_format == 'SCENE':
		if original_format not in IMAGE_FORMATS:
			print('{} Format is not an image format. Not Saving'.format(
				original_format))
			return
	elif bpy.context.scene.auto_save_render_settings.auto_save_format == 'PNG':
		rndr.image_settings.file_format = 'PNG'
	elif bpy.context.scene.auto_save_render_settings.auto_save_format == 'OPEN_EXR_MULTILAYER':
		rndr.image_settings.file_format = 'OPEN_EXR_MULTILAYER'
	elif bpy.context.scene.auto_save_render_settings.auto_save_format == 'JPEG':
		rndr.image_settings.file_format = 'JPEG'
	extension = rndr.file_extension

	# Set location and file name variables
	# blendname = basename(bpy.data.filepath).rpartition('.')[0]
	# blendname = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
	blendname = os.path.splitext(os.path.basename(bpy.data.filepath))[0].replace(' ', '')

	# filepath = os.path.join(os.path.dirname(bpy.data.filepath), blendname)
	if len(bpy.context.scene.auto_save_render_settings.auto_save_customdirectory) <= 1:
		filepath = os.path.join(os.path.dirname(bpy.data.filepath), blendname)
		# filepath = os.path.splitext(bpy.data.filepath)[0]
	else:
		filepath = bpy.context.scene.auto_save_render_settings.auto_save_customdirectory

	# Creates the project subfolder if it doesn't already exist
	if not os.path.exists(filepath):
		os.mkdir(filepath)

	# Build initial output file name components
	save_name = blendname
	if bpy.context.scene.auto_save_render_settings.auto_save_include_cameraname:
		# save_name += '-' + bpy.context.scene.camera.name
		save_name += '-' + bpy.context.scene.camera.name.replace(' ', '')
	if bpy.context.scene.auto_save_render_settings.auto_save_include_framenumber:
		# save_name += '-' + str(bpy.context.scene.frame_current).zfill(5)
		save_name += '-' + format(bpy.context.scene.frame_current, '05')
		# save_name += '-frame' + format(bpy.context.scene.frame_current, '05')
	if bpy.context.scene.auto_save_render_settings.auto_save_include_renderengine:
		save_name += '-' + bpy.context.engine.replace('BLENDER_', '')

	# Generate the serial number
	# Finds all of the image files that start with blendname
	files = [f for f in os.listdir(filepath)
			if f.startswith(blendname)
			and f.lower().endswith(IMAGE_EXTENSIONS)]

	# Searches the file collection and returns the next highest number as a 4 digit string
	def save_number_from_files(files):
		highest = 0
		if files:
			for f in files:
				# find last numbers in the filename
				suffix = findall(r'\d+', f.split(blendname)[-1])
				if suffix:
					if int(suffix[-1]) > highest:
						highest = int(suffix[-1])
		return str(highest+1).zfill(4)

	# Finish building the output file name
	if bpy.context.scene.auto_save_render_settings.auto_save_numbering == 'SERIAL':
		save_name += '-' + save_number_from_files(files)
	else:
		save_name += '-' + datetime.datetime.now().strftime('%Y_%m_%d-%H_%M_%S')
	save_name += extension
	save_name = os.path.join(filepath, save_name)

	image = bpy.data.images['Render Result']
	if not image:
		print('Auto Save: Render Result not found. Image not saved')
		return

	print('Auto_Save:', save_name)
	image.save_render(save_name, scene=None)

	rndr.image_settings.file_format = original_format
	rndr.image_settings.color_mode = original_colormode
	rndr.image_settings.color_depth = original_colordepth

###########################################################################

def set_directory(self, value):
	path = Path(value)
	if path.is_dir():
		self["auto_save_customdirectory"] = value

def get_directory(self):
	return self.get("auto_save_customdirectory", bpy.context.scene.auto_save_render_settings.bl_rna.properties["auto_save_customdirectory"].default)

###########################################################################

class AutoSaveRenderSettings(bpy.types.PropertyGroup):
	enable_auto_save_render: bpy.props.BoolProperty(
		name="Enable/disable automatic saving of rendered images",
		description="Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
		default=False)
	auto_save_customdirectory: bpy.props.StringProperty(
		name="Custom Save Directory",
		description="Leave a single forward slash to auto generate folders alongside the project file",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH",
		set=set_directory,
		get=get_directory)
	auto_save_include_cameraname: bpy.props.BoolProperty(
		name="Camera Name",
		description="Include the camera name in the auto saved file name",
		default=True)
	auto_save_include_framenumber: bpy.props.BoolProperty(
		name="Frame Number",
		description="Include the frame number in the auto saved file name",
		default=True)
	auto_save_include_renderengine: bpy.props.BoolProperty(
		name="Render Engine",
		description="Include the current render engine code in the auto saved file name",
		default=False)
	auto_save_include_rendertime: bpy.props.BoolProperty(
		name="Render Time",
		description="Include the number of seconds spent rendering in the auto saved file name",
		default=False)
	auto_save_numbering: bpy.props.EnumProperty(
		name='File Numbering',
		description='Serial or time stamp, ensuring every file is saved without overwriting',
		items=[
			('SERIAL', 'Serial Number', 'Saves images with globally sequential serial numbers'),
			# ('INDIVIDUAL', 'group serial numbers', 'saves images with sequential serial numbers per camera and/or frame'),
			('TIME', 'Time Stamp', 'Saves images with the local date and time'),
			],
		default='SERIAL')
	auto_save_format: bpy.props.EnumProperty(
		name='File Format',
		description='Image format used for the automatically saved render files',
		items=[
			('SCENE', 'Project Setting', 'Format set in output panel'),
			('PNG', 'PNG', 'Save as png'),
			('JPEG', 'JPEG', 'Save as jpeg'),
			('OPEN_EXR_MULTILAYER', 'OpenEXR MultiLayer', 'Save as multilayer exr'),
			],
		default='JPEG')

class RENDER_PT_auto_save_render(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Auto Save Render"
	bl_parent_id = "RENDER_PT_output"
	bl_options = {'DEFAULT_CLOSED'}
	compatible_render_engines = {'BLENDER_RENDER', 'BLENDER_OPENGL', 'BLENDER_WORKBENCH', 'BLENDER_EEVEE', 'CYCLES', 'RPR', 'LUXCORE'}

	@classmethod
	def poll(cls, context):
		return (context.engine in cls.compatible_render_engines)

	def draw_header(self, context):
		self.layout.prop(context.scene.auto_save_render_settings, 'enable_auto_save_render', text='')

	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		layout.prop(context.scene.auto_save_render_settings, 'auto_save_customdirectory', text='')

		layout.use_property_split = True
		col = layout.column(align=True)
		row = col.row(align=True)
		row.prop(context.scene.auto_save_render_settings, 'auto_save_include_cameraname')
		row.prop(context.scene.auto_save_render_settings, 'auto_save_include_framenumber')
		row.prop(context.scene.auto_save_render_settings, 'auto_save_include_renderengine')
		# row.prop(context.scene.auto_save_render_settings, 'auto_save_include_rendertime')

		# Until render time is added to the Python API in Blender, or a timing system is built, this will be disabled
		subrow = row.column(align=True)
		subrow.active = False
		subrow.prop(context.scene.auto_save_render_settings, 'auto_save_include_rendertime')

		layout.prop(context.scene.auto_save_render_settings, 'auto_save_numbering')
		layout.prop(context.scene.auto_save_render_settings, 'auto_save_format')

classes = (AutoSaveRenderSettings, RENDER_PT_auto_save_render)

def register():
	for cls in classes:
		bpy.utils.register_class(cls)
	bpy.types.Scene.auto_save_render_settings = bpy.props.PointerProperty(type=AutoSaveRenderSettings)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.append(auto_save_render)
	bpy.app.handlers.render_cancel.append(auto_save_render)
	bpy.app.handlers.render_complete.append(auto_save_render)

def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
	del bpy.types.Scene.auto_save_render_settings
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.remove(auto_save_render)
	bpy.app.handlers.render_cancel.remove(auto_save_render)
	bpy.app.handlers.render_complete.remove(auto_save_render)

if __name__ == "__main__":
	register()
