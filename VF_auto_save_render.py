bl_info = {
	"name": "VF Auto Save Render",
	"author": "John Einselen - Vectorform LLC, based on original work by tstscr(florianfelix)",
	"version": (0, 6),
	"blender": (2, 80, 0),
	"location": "Rendertab > Output Panel > Subpanel",
	"description": "Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
	"warning": "inexperienced developer, use at your own risk",
	"wiki_url": "",
	"tracker_url": "",
	"category": "Render"}

# Based on the following resources:
# https://gist.github.com/egetun/1224aa600a32bd38fa771df463796977
# https://github.com/patrickhill/blender-datestamper/blob/master/render_auto_save_with_datestamp.py
# https://gist.github.com/robertguetzkow/8dacd4b565538d657b72efcaf0afe07e
# https://blender.stackexchange.com/questions/6842/how-to-get-the-directory-of-open-blend-file-from-python
# https://github.com/AlreadyLegendary/Render-time-estimator

import os
import datetime
import time
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

###########################################################################
# Auto save render function

@persistent
def auto_save_render(scene):
	if not bpy.context.scene.auto_save_render_settings.enable_auto_save_render or not bpy.data.filepath:
		return
	rndr = scene.render

	# Calculate elapsed render time
	render_time = round(time.time() - float(bpy.context.scene.auto_save_render_settings.start_date), 2)

	# Save original file format settings
	original_format = rndr.image_settings.file_format
	original_colormode = rndr.image_settings.color_mode
	original_colordepth = rndr.image_settings.color_depth

	# Set up render output formatting
	if bpy.context.scene.auto_save_render_settings.file_format == 'SCENE':
		if original_format not in IMAGE_FORMATS:
			print('{} Format is not an image format. Not Saving'.format(
				original_format))
			return
	elif bpy.context.scene.auto_save_render_settings.file_format == 'JPEG':
		rndr.image_settings.file_format = 'JPEG'
	elif bpy.context.scene.auto_save_render_settings.file_format == 'PNG':
		rndr.image_settings.file_format = 'PNG'
	elif bpy.context.scene.auto_save_render_settings.file_format == 'OPEN_EXR_MULTILAYER':
		rndr.image_settings.file_format = 'OPEN_EXR_MULTILAYER'
	extension = rndr.file_extension

	# Set location and file name variables
	blendname = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
	# blendname = os.path.splitext(os.path.basename(bpy.data.filepath))[0].replace(' ', '')

	if len(bpy.context.scene.auto_save_render_settings.customdirectory) <= 1:
		filepath = os.path.join(os.path.dirname(bpy.data.filepath), blendname)
	else:
		filepath = bpy.context.scene.auto_save_render_settings.customdirectory

	# Create the project subfolder if it doesn't already exist
	if not os.path.exists(filepath):
		os.mkdir(filepath)

	# Build initial output file name components
	save_name = ''
	if bpy.context.scene.auto_save_render_settings.include_projectname:
		save_name = blendname
	if bpy.context.scene.auto_save_render_settings.include_activeitem and bpy.context.view_layer.objects.active:
		if bpy.context.scene.auto_save_render_settings.include_projectname:
			save_name += '-'
		# save_name += '-Selected'
		save_name += bpy.context.view_layer.objects.active.name
		# save_name += '-' + bpy.context.view_layer.objects.active.name.replace(' ', '')
	if bpy.context.scene.auto_save_render_settings.include_cameraname:
		save_name += '-' + bpy.context.scene.camera.name
		# save_name += '-' + bpy.context.scene.camera.name.replace(' ', '')
	if bpy.context.scene.auto_save_render_settings.include_framenumber:
		save_name += '-' + format(bpy.context.scene.frame_current, '05')
	if bpy.context.scene.auto_save_render_settings.include_renderengine:
		save_name += '-' + bpy.context.engine.replace('BLENDER_', '')
	if bpy.context.scene.auto_save_render_settings.include_rendertime:
		save_name += '-' + str(render_time)

	# Generate the serial number
		# Finds all of the image files in the selected directory that start with blendname
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
	if bpy.context.scene.auto_save_render_settings.include_numbering:
		if bpy.context.scene.auto_save_render_settings.numbering_type == 'SERIAL':
			save_name += '-' + save_number_from_files(files)
		else:
			save_name += '-' + datetime.datetime.now().strftime('%Y_%m_%d-%H_%M_%S')
	save_name += extension
	save_name = os.path.join(filepath, save_name)

	# Save image file
	image = bpy.data.images['Render Result']
	if not image:
		print('Auto Save: Render Result not found. Image not saved')
		return

	print('Auto_Save:', save_name)
	image.save_render(save_name, scene=None)

	# Restore original user settings for render output (otherwise a temporary JPEG format above will overwrite the final PNG output colour mode and depth settings)
	rndr.image_settings.file_format = original_format
	rndr.image_settings.color_mode = original_colormode
	rndr.image_settings.color_depth = original_colordepth

###########################################################################
# Start time function

@persistent
def render_start_time(scene):
	# Saves start time in seconds as a string to the addon settings
	bpy.context.scene.auto_save_render_settings.start_date = str(time.time())

###########################################################################
# UI input functions

def set_directory(self, value):
	path = Path(value)
	if path.is_dir():
		self["customdirectory"] = value

def get_directory(self):
	return self.get("customdirectory", bpy.context.scene.auto_save_render_settings.bl_rna.properties["customdirectory"].default)

###########################################################################
# UI settings and rendering classes

class AutoSaveRenderSettings(bpy.types.PropertyGroup):
	enable_auto_save_render: bpy.props.BoolProperty(
		name="Enable/disable automatic saving of rendered images",
		description="Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
		default=False)
	customdirectory: bpy.props.StringProperty(
		name="Custom Save Directory",
		description="Leave a single forward slash to auto generate folders alongside the project file",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH",
		set=set_directory,
		get=get_directory)
	include_projectname: bpy.props.BoolProperty(
		name="Project Name",
		description="Include the name of the name of the project in the auto saved file name (recommended)",
		default=True)
	include_activeitem: bpy.props.BoolProperty(
		name="Active Item",
		description="Include the name of the currently active item in the auto saved file name",
		default=False)
	include_cameraname: bpy.props.BoolProperty(
		name="Camera Name",
		description="Include the camera name in the auto saved file name",
		default=True)
	include_framenumber: bpy.props.BoolProperty(
		name="Frame Number",
		description="Include the frame number in the auto saved file name",
		default=True)
	include_renderengine: bpy.props.BoolProperty(
		name="Render Engine",
		description="Include the current render engine code in the auto saved file name",
		default=False)
	include_rendertime: bpy.props.BoolProperty(
		name="Render Time",
		description="Include the number of seconds spent rendering in the auto saved file name",
		default=False)
	include_numbering: bpy.props.BoolProperty(
		name="Enable Numbering",
		description="Include serial number or time stamp in the auto saved file name (recommended)",
		default=True)
	numbering_type: bpy.props.EnumProperty(
		name='File Numbering',
		description='Serial or time stamp, ensuring every file is saved without overwriting',
		items=[
			('SERIAL', 'Serial Number', 'Saves images with globally sequential serial numbers'),
			# ('INDIVIDUAL', 'group serial numbers', 'saves images with sequential serial numbers per camera and/or frame'),
			('TIME', 'Time Stamp', 'Saves images with the local date and time'),
			],
		default='SERIAL')
	file_format: bpy.props.EnumProperty(
		name='File Format',
		description='Image format used for the automatically saved render files',
		# icon='IMAGE', #'IMAGE_DATA' 'IMAGE_BACKGROUND' 'FILE_IMAGE'
		items=[
			('SCENE', 'Project Setting', 'Format set in output panel'),
			('PNG', 'PNG', 'Save as png'),
			('JPEG', 'JPEG', 'Save as jpeg'),
			('OPEN_EXR_MULTILAYER', 'OpenEXR MultiLayer', 'Save as multilayer exr'),
			],
		default='JPEG')
	start_date: bpy.props.StringProperty(
		name="Render Start Date",
		description="Stores the date as a string for when rendering began",
		default="")

class RENDER_PT_auto_save_render(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Auto Save Render"
	bl_parent_id = "RENDER_PT_output"
	bl_options = {'DEFAULT_CLOSED'}

	# Check for engine compatibility
	# This is currently disabled for simplicity
	# compatible_render_engines = {'BLENDER_RENDER', 'BLENDER_OPENGL', 'BLENDER_WORKBENCH', 'BLENDER_EEVEE', 'CYCLES', 'RPR', 'LUXCORE'}
	# @classmethod
	# def poll(cls, context):
		# return (context.engine in cls.compatible_render_engines)

	def draw_header(self, context):
		self.layout.prop(context.scene.auto_save_render_settings, 'enable_auto_save_render', text='')

	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		layout.prop(context.scene.auto_save_render_settings, 'customdirectory', text='')

		layout.use_property_split = True
		col = layout.column(align=True)
		row = col.row(align=True)
		row.prop(context.scene.auto_save_render_settings, 'include_projectname')
		row.prop(context.scene.auto_save_render_settings, 'include_activeitem')
		row.prop(context.scene.auto_save_render_settings, 'include_cameraname')
		row.prop(context.scene.auto_save_render_settings, 'include_framenumber')
		row.prop(context.scene.auto_save_render_settings, 'include_renderengine')
		row.prop(context.scene.auto_save_render_settings, 'include_rendertime')
		row.prop(context.scene.auto_save_render_settings, 'include_numbering')

		layout.prop(context.scene.auto_save_render_settings, 'numbering_type')
		layout.prop(context.scene.auto_save_render_settings, 'file_format')

classes = (AutoSaveRenderSettings, RENDER_PT_auto_save_render)

###########################################################################
# Addon registration functions

def register():
	for cls in classes:
		bpy.utils.register_class(cls)
	bpy.types.Scene.auto_save_render_settings = bpy.props.PointerProperty(type=AutoSaveRenderSettings)
	# Using init instead of pre means that the entire animation render time is tracked instead of just the final frame
	# bpy.app.handlers.render_pre.append(render_start_time)
	bpy.app.handlers.render_init.append(render_start_time)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.append(auto_save_render)
	bpy.app.handlers.render_cancel.append(auto_save_render)
	bpy.app.handlers.render_complete.append(auto_save_render)

def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
	del bpy.types.Scene.auto_save_render_settings
	# Using init instead of pre means that the entire animation render time is tracked instead of just the final frame
	# bpy.app.handlers.render_pre.remove(render_start_time)
	bpy.app.handlers.render_init.remove(render_start_time)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.remove(auto_save_render)
	bpy.app.handlers.render_cancel.remove(auto_save_render)
	bpy.app.handlers.render_complete.remove(auto_save_render)

if __name__ == "__main__":
	register()
