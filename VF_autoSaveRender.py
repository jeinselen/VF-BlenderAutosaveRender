bl_info = {
	"name": "VF Auto Save Render",
	"author": "John Einselen - Vectorform LLC, based on work by tstscr(florianfelix)",
	"version": (1, 5, 0),
	"blender": (2, 80, 0),
	"location": "Rendertab > Output Panel > Subpanel",
	"description": "Automatically saves rendered images with custom naming convention",
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
# https://www.geeksforgeeks.org/python-program-to-convert-seconds-into-hours-minutes-and-seconds/

import os
import datetime
import time
import bpy
from bpy.app.handlers import persistent
from re import findall, search, M as multiline
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
	# Calculate elapsed render time
	render_time = round(time.time() - float(bpy.context.scene.auto_save_render_settings.start_date), 2)

	# Update total render time
	bpy.context.scene.auto_save_render_settings.total_render_time = bpy.context.scene.auto_save_render_settings.total_render_time + render_time

	# Restore unprocessed file path if processing is enabled
	if bpy.context.preferences.addons['VF_autoSaveRender'].preferences.filter_output_file_path and bpy.context.scene.auto_save_render_settings.output_file_path:
		scene.render.filepath = bpy.context.scene.auto_save_render_settings.output_file_path

	# Stop here if the auto output is disabled
	if not bpy.context.scene.auto_save_render_settings.enable_auto_save_render or not bpy.data.filepath:
		return {'CANCELLED'}

	# Save original file format settings
	original_format = scene.render.image_settings.file_format
	original_colormode = scene.render.image_settings.color_mode
	original_colordepth = scene.render.image_settings.color_depth

	# Set up render output formatting
	if bpy.context.scene.auto_save_render_settings.file_format == 'SCENE':
		if original_format not in IMAGE_FORMATS:
			print('VF Auto Save Render: {} is not an image format, not saving'.format(original_format))
			return
	elif bpy.context.scene.auto_save_render_settings.file_format == 'JPEG':
		scene.render.image_settings.file_format = 'JPEG'
	elif bpy.context.scene.auto_save_render_settings.file_format == 'PNG':
		scene.render.image_settings.file_format = 'PNG'
	elif bpy.context.scene.auto_save_render_settings.file_format == 'OPEN_EXR_MULTILAYER':
		scene.render.image_settings.file_format = 'OPEN_EXR_MULTILAYER'
	extension = scene.render.file_extension

	# Set location and file name variables
	projectname = os.path.splitext(os.path.basename(bpy.data.filepath))[0]

	if len(bpy.context.scene.auto_save_render_settings.file_location) <= 1:
		filepath = os.path.join(os.path.dirname(bpy.data.filepath), projectname)
	else:
		filepath = bpy.context.scene.auto_save_render_settings.file_location

	# Create the project subfolder if it doesn't already exist
	if not os.path.exists(filepath):
		os.mkdir(filepath)

	# Generate the serial number
		# Finds all of the image files in the selected directory that start with projectname
	files = [f for f in os.listdir(filepath)
			if f.startswith(projectname)
			and f.lower().endswith(IMAGE_EXTENSIONS)]

		# Searches the file collection and returns the next highest number as a 4 digit string
	def save_number_from_files(files):
		highest = 0
		if files:
			for f in files:
				# find filenames that end with four or more digits
				suffix = findall(r'\d{4,}$', os.path.splitext(f)[0].split(projectname)[-1], multiline)
				if suffix:
					if int(suffix[-1]) > highest:
						highest = int(suffix[-1])
		return format(highest+1, '04')

	# Create the rest of the file name components (projectname has already been created above)
	itemname = bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else 'None'
	cameraname = bpy.context.scene.camera.name
	framenumber = format(bpy.context.scene.frame_current, '04')
	renderengine = bpy.context.engine.replace('BLENDER_', '')
	rendertime = str(render_time)
	datenumber = datetime.datetime.now().strftime('%Y-%m-%d')
	timenumber = datetime.datetime.now().strftime('%H-%M-%S')
	serialnumber = save_number_from_files(files)

	# Compile the output file name
	if bpy.context.scene.auto_save_render_settings.file_name_type == 'SERIAL':
		filename = projectname + '-' + serialnumber
	elif bpy.context.scene.auto_save_render_settings.file_name_type == 'DATE':
		filename = projectname + ' ' + datenumber + ' ' + timenumber
	elif bpy.context.scene.auto_save_render_settings.file_name_type == 'RENDER':
		filename = projectname + ' ' + renderengine + ' ' + rendertime
	else:
		filename = bpy.context.scene.auto_save_render_settings.file_name_custom
		# Using "replace" instead of "format" because format fails ungracefully when an exact match isn't found (unusable behaviour in this situation)
		filename = filename.replace("{project}", projectname)
		filename = filename.replace("{item}", itemname)
		filename = filename.replace("{camera}", cameraname)
		filename = filename.replace("{frame}", framenumber)
		filename = filename.replace("{renderengine}", renderengine)
		filename = filename.replace("{rendertime}", rendertime)
		filename = filename.replace("{date}", datenumber)
		filename = filename.replace("{time}", timenumber)
		if '{serial}' in bpy.context.scene.auto_save_render_settings.file_name_custom:
			filename = filename.replace("{serial}", format(bpy.context.scene.auto_save_render_settings.file_name_serial, '04'))
			bpy.context.scene.auto_save_render_settings.file_name_serial += 1

	# Add extension
	filename += extension

	# Combine file path and file name using system separator
	filename = os.path.join(filepath, filename)

	# Save image file
	image = bpy.data.images['Render Result']
	if not image:
		print('VF Auto Save Render: Render Result not found. Image not saved')
		return

	image.save_render(filename, scene=None)

	# Restore original user settings for render output
	scene.render.image_settings.file_format = original_format
	scene.render.image_settings.color_mode = original_colormode
	scene.render.image_settings.color_depth = original_colordepth

	return {'FINISHED'}

###########################################################################
# Start time function

@persistent
def auto_save_render_start(scene):
	# Save start time in seconds as a string to the addon settings
	bpy.context.scene.auto_save_render_settings.start_date = str(time.time())

	# Filter output file path if enabled
	if bpy.context.preferences.addons['VF_autoSaveRender'].preferences.filter_output_file_path:
		# Save original file path
		bpy.context.scene.auto_save_render_settings.output_file_path = filepath = scene.render.filepath

		# Process file path variables
		filepath = filepath.replace("{project}", os.path.splitext(os.path.basename(bpy.data.filepath))[0])
		filepath = filepath.replace("{item}", bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else 'None')
		filepath = filepath.replace("{camera}", bpy.context.scene.camera.name)
		filepath = filepath.replace("{renderengine}", bpy.context.engine.replace('BLENDER_', ''))
		filepath = filepath.replace("{date}", datetime.datetime.now().strftime('%Y-%m-%d'))
		filepath = filepath.replace("{time}", datetime.datetime.now().strftime('%H-%M-%S'))
		if '{serial}' in filepath:
			filepath = filepath.replace("{serial}", format(bpy.context.scene.auto_save_render_settings.output_file_serial, '04'))
			bpy.context.scene.auto_save_render_settings.output_file_serial += 1

		# Replace scene filepath output with the processed version
		scene.render.filepath = filepath

###########################################################################
# Time conversion functions, because datetime doesn't like zero-numbered days or hours over 24

# Converts float into HH:MM:SS.## format, hours expand indefinitely (will not roll over into days)
def secondsToReadable(seconds):
	seconds, decimals = divmod(seconds, 1)
	minutes, seconds = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)
	return "%d:%02d:%02d.%02d" % (hours, minutes, seconds, round(decimals*100))

# Converts string of HH:MM:SS.## format into float
def readableToSeconds(readable):
	hours, minutes, seconds = readable.split(':')
	return int(hours)*3600 + int(minutes)*60 + float(seconds)

###########################################################################
# UI input functions

def set_directory(self, value):
	path = Path(value)
	if path.is_dir():
		self["file_location"] = value

def get_directory(self):
	return self.get("file_location", bpy.context.scene.auto_save_render_settings.bl_rna.properties["file_location"].default)

###########################################################################
# User preferences and UI rendering class

class AutoSaveRenderPreferences(bpy.types.AddonPreferences):
	bl_idname = __name__

	show_total_render_time: bpy.props.BoolProperty(
		name="Show Total Render Time",
		description='Displays the total amount of time spent rendering a project in the output panel',
		default=False)
	filter_output_file_path: bpy.props.BoolProperty(
		name="Process Output File Path",
		description='Implements some of the same keywords used in the custom naming scheme in the Output directory',
		default=False)
	# default_file_name_custom: bpy.props.StringProperty(
	# 	name="Custom String",
	# 	description="Options: {project} {item} {camera} {frame} {renderengine} {rendertime} {date} {time} {serial}",
	# 	default="{project}-{serial}-{renderengine}-{rendertime}",
	# 	maxlen=4096)

	def draw(self, context):
		layout = self.layout
		# layout.label(text="Addon Default Preferences")
		grid = layout.grid_flow(row_major=True)
		grid.prop(self, "show_total_render_time")
		if bpy.context.preferences.addons['VF_autoSaveRender'].preferences.show_total_render_time:
			grid.prop(context.scene.auto_save_render_settings, 'total_render_time')
		layout.prop(self, "filter_output_file_path")
		# if bpy.context.preferences.addons['VF_autoSaveRender'].preferences.filter_output_file_path:
			# box = layout.box()
			# box.label(text="Output Path Variables: {project} {item} {camera} {renderengine} {date} {time} {serial}")
		# layout.prop(self, 'default_file_name_custom')

###########################################################################
# Project settings and UI rendering classes

class AutoSaveRenderSettings(bpy.types.PropertyGroup):
	enable_auto_save_render: bpy.props.BoolProperty(
		name="Enable/disable automatic saving of rendered images",
		description="Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
		default=True)
	file_location: bpy.props.StringProperty(
		name="Autosave Location",
		description="Leave a single forward slash to auto generate folders alongside project files",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH",
		set=set_directory,
		get=get_directory)
	file_name_type: bpy.props.EnumProperty(
		name='File Name',
		description='Auto saves files with the project name and serial number, project name and date, or custom naming pattern',
		items=[
			('SERIAL', 'Project Name + Serial Number', 'Save files with a sequential serial number'),
			('DATE', 'Project Name + Date & Time', 'Save files with the local date and time'),
			('RENDER', 'Project Name + Render Engine + Render Time', 'Save files with the render engine and render time'),
			('CUSTOM', 'Custom String', 'Save files with a custom string format'),
			],
		default='SERIAL')
	file_name_custom: bpy.props.StringProperty(
		name="Custom String",
		description="Options: {project} {item} {camera} {frame} {renderengine} {rendertime} {date} {time} {serial}",
		default="{project}-{serial}-{renderengine}-{rendertime}",
		maxlen=4096)
	file_name_serial: bpy.props.IntProperty(
		name="Serial Number",
		description="Current serial number, automatically increments with every render")
	file_format: bpy.props.EnumProperty(
		name='File Format',
		description='Image format used for the automatically saved render files',
		items=[
			('SCENE', 'Project Setting', 'Same format as set in output panel'),
			('PNG', 'PNG', 'Save as png'),
			('JPEG', 'JPEG', 'Save as jpeg'),
			('OPEN_EXR_MULTILAYER', 'OpenEXR MultiLayer', 'Save as multilayer exr'),
			],
		default='JPEG')
	start_date: bpy.props.StringProperty(
		name="Render Start Date",
		description="Stores the date when rendering started in seconds as a string",
		default="")
	total_render_time: bpy.props.FloatProperty(
		name="Total Render Time",
		description="Stores the total time spent rendering in seconds",
		default=0)

	# Variables for output file path processing
	output_file_path: bpy.props.StringProperty(
		name="Original Render Path",
		description="Stores the original render path as a string to allow for successful restoration after rendering completes",
		default="")
	output_file_serial: bpy.props.IntProperty(
		name="Serial Number",
		description="Current serial number, automatically increments with every render")


class RENDER_PT_auto_save_render_path(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Output Path Variables"
	bl_parent_id = "RENDER_PT_output"
	bl_options = {'HIDE_HEADER'}

	# def draw_header(self, context):
		# self.layout.prop(bpy.context.scene.render, 'use_border', text='')

	def draw(self, context):
		if bpy.context.preferences.addons['VF_autoSaveRender'].preferences.filter_output_file_path:
			layout = self.layout
			layout.use_property_decorate = False  # No animation
			layout.use_property_split = True
			if '{serial}' in bpy.context.scene.render.filepath:
				layout.prop(context.scene.auto_save_render_settings, 'output_file_serial')
			box = layout.box()
			box.label(text="Output Path Variables: {project} {item} {camera} {renderengine} {date} {time} {serial}")

class RENDER_PT_auto_save_render(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Auto Save Render"
	bl_parent_id = "RENDER_PT_output"
	# bl_options = {'DEFAULT_CLOSED'}

	# Check for engine compatibility
	# compatible_render_engines = {'BLENDER_RENDER', 'BLENDER_OPENGL', 'BLENDER_WORKBENCH', 'BLENDER_EEVEE', 'CYCLES', 'RPR', 'LUXCORE'}

	# @classmethod
	# def poll(cls, context):
		# return (context.engine in cls.compatible_render_engines)

	def draw_header(self, context):
		self.layout.prop(context.scene.auto_save_render_settings, 'enable_auto_save_render', text='')

	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		layout.prop(context.scene.auto_save_render_settings, 'file_location', text='')
		layout.use_property_split = True
		layout.prop(context.scene.auto_save_render_settings, 'file_name_type', icon='FILE_TEXT')
		if bpy.context.scene.auto_save_render_settings.file_name_type == 'CUSTOM':
			# this is intended as a semi-hacky way to override the initial custom string with a global preset instead of relying on get/set
			# if '{unset}' in bpy.context.scene.auto_save_render_settings.file_name_custom:
				# bpy.context.scene.auto_save_render_settings.file_name_custom = bpy.context.preferences.addons['VF_autoSaveRender'].preferences.default_file_name_custom
			layout.use_property_split = True
			layout.prop(context.scene.auto_save_render_settings, 'file_name_custom')
			if '{serial}' in bpy.context.scene.auto_save_render_settings.file_name_custom:
				layout.use_property_split = True
				layout.prop(context.scene.auto_save_render_settings, 'file_name_serial')
		layout.prop(context.scene.auto_save_render_settings, 'file_format', icon='FILE_IMAGE')
		if bpy.context.preferences.addons['VF_autoSaveRender'].preferences.show_total_render_time:
			box = layout.box()
			# if bpy.context.scene.auto_save_render_settings.file_name_type == 'CUSTOM':
				# box.label(text="Custom String Variables: {project} {item} {camera} {frame} {renderengine} {rendertime} {date} {time} {serial}")
			box.label(text="Total time spent rendering: "+secondsToReadable(bpy.context.scene.auto_save_render_settings.total_render_time))

classes = (AutoSaveRenderPreferences, AutoSaveRenderSettings, RENDER_PT_auto_save_render_path, RENDER_PT_auto_save_render)

###########################################################################
# Addon registration functions

def register():
	for cls in classes:
		bpy.utils.register_class(cls)
	bpy.types.Scene.auto_save_render_settings = bpy.props.PointerProperty(type=AutoSaveRenderSettings)
	# Using init instead of pre means that the entire animation render time is tracked instead of just the final frame
	# bpy.app.handlers.render_pre.append(auto_save_render_start)
	bpy.app.handlers.render_init.append(auto_save_render_start)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.append(auto_save_render)
	bpy.app.handlers.render_cancel.append(auto_save_render)
	bpy.app.handlers.render_complete.append(auto_save_render)

def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
	del bpy.types.Scene.auto_save_render_settings
	# Using init instead of pre means that the entire animation render time is tracked instead of just the final frame
	# bpy.app.handlers.render_pre.remove(auto_save_render_start)
	bpy.app.handlers.render_init.remove(auto_save_render_start)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.remove(auto_save_render)
	bpy.app.handlers.render_cancel.remove(auto_save_render)
	bpy.app.handlers.render_complete.remove(auto_save_render)

if __name__ == "__main__":
	register()
