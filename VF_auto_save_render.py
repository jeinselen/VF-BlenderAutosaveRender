bl_info = {
	"name": "VF Auto Save Render",
	"author": "John Einselen - Vectorform LLC, based on original work by tstscr(florianfelix)",
	"version": (1, 2),
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
			if f.lower().endswith(IMAGE_EXTENSIONS)]
			# and f.startswith(projectname)

		# Searches the file collection and returns the next highest number as a 4 digit string
	def save_number_from_files(files):
		highest = 0
		if files:
			for f in files:
				# find last numbers in the filename
				suffix = findall(r'\d+', f.split(projectname)[-1])
				if suffix:
					if int(suffix[-1]) > highest:
						highest = int(suffix[-1])
		# return str(highest+1).zfill(4)
		return format(highest+1, '04')

	# Create the rest of the file name components
	# projectname has already been created above
	if bpy.context.view_layer.objects.active:
		itemname = bpy.context.view_layer.objects.active.name
	else:
		itemname = 'None'
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
		filename = filename.replace("{serial}", serialnumber)

	# Add extension
	filename += extension

	# Combine file path and file name
	filename = os.path.join(filepath, filename)

	# Save image file
	image = bpy.data.images['Render Result']
	if not image:
		print('Auto Save: Render Result not found. Image not saved')
		return

	print('Auto_Save:', filename)
	image.save_render(filename, scene=None)

	# Save log file
	if bpy.context.scene.auto_save_render_settings.save_log:
		# Log file settings
		logpath = os.path.join(filepath, projectname + '-rendertime.txt')
		logtitle = 'Total render time '
		logtime = 0.00

		# Get previous time spent rendering, if log file exists
		if os.path.exists(logpath):
			with open(logpath) as filein:
				logtime = filein.read().replace(logtitle, '')
				logtime = readableToSeconds(logtime)

		# Add the newest segment of render time
		logtime += float(render_time)

		# Convert into formatted string
		logtime = secondsToReadable(logtime)

		# Write log file
		with open(logpath, 'w') as fileout:
			fileout.write(logtitle + logtime)

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
# Time conversion functions, because datetime doesn't like zero-numbered days or hours over 24
# https://www.geeksforgeeks.org/python-program-to-convert-seconds-into-hours-minutes-and-seconds/

def secondsToReadable(seconds):
	seconds, decimals = divmod(seconds, 1)
	minutes, seconds = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)
	return "%d:%02d:%02d.%02d" % (hours, minutes, seconds, round(decimals*100))

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
# UI settings and rendering classes

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
		description="Options: {project} {item} {camera} {frame} {renderengine} {rendertime} {date} {time} {serial} Note: a serial number must be placed at the very end",
		default="AutoSave-{renderengine}-{rendertime}-{serial}",
		maxlen=4096)
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
	save_log: bpy.props.BoolProperty(
		name="Save text file with total render time",
		description="Saves a text file alongside the project with the total time spent rendering",
		default=True)
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
		layout.prop(context.scene.auto_save_render_settings, 'file_location', text='')
		layout.use_property_split = True
		layout.prop(context.scene.auto_save_render_settings, 'file_name_type', icon='FILE_TEXT')
		if bpy.context.scene.auto_save_render_settings.file_name_type == 'CUSTOM':
			layout.use_property_split = True
			layout.prop(context.scene.auto_save_render_settings, 'file_name_custom', text='')
		layout.prop(context.scene.auto_save_render_settings, 'file_format', icon='FILE_IMAGE')
		layout.prop(context.scene.auto_save_render_settings, 'save_log')

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
