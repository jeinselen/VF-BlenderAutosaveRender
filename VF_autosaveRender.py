bl_info = {
	"name": "VF Autosave Render + Output Variables",
	"author": "John Einselen - Vectorform LLC, based on work by tstscr(florianfelix)",
	"version": (2, 4, 0),
	"blender": (3, 2, 0),
	"location": "Scene Output Properties > Output Panel > Autosave Render",
	"description": "Automatically saves rendered images with custom naming",
	"warning": "inexperienced developer, use at your own risk",
	"wiki_url": "",
	"tracker_url": "",
	"category": "Render"}

import bpy
from bpy.app.handlers import persistent
import datetime
import json
import os
from pathlib import Path
import platform
from re import findall, search, sub, M as multiline
import time
# FFmpeg system access
import subprocess
from shutil import which
# Pushover notifications
import requests

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
	'tif')
FFMPEG_FORMATS = (
	'BMP',
	'PNG',
	'JPEG',
	'DPX',
	'OPEN_EXR',
	'TIFF')

variableArray = ["title,Project,SCENE_DATA", "{project}", "{scene}", "{collection}", "{camera}", "{item}", "{material}",
				"title,Rendering,CAMERA_DATA", "{renderengine}", "{device}", "{samples}", "{features}", "{rendertime}",
				"title,System,DESKTOP", "{host}", "{platform}", "{version}",
				"title,Identifiers,COPY_ID", "{date}", "{y},{m},{d}", "{time}", "{H},{M},{S}", "{serial}", "{frame}"]

###########################################################################
# Start time function

@persistent
def autosave_render_start(scene):
	# Set video sequence tracking (separate from render active below)
	bpy.context.scene.autosave_render_settings.autosave_video_sequence = False
	bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = False
	
	# Set estimated render time active to false (must render at least one frame before estimating time remaining)
	bpy.context.scene.autosave_render_settings.estimated_render_time_active = False
	
	# Save start time in seconds as a string to the addon settings
	bpy.context.scene.autosave_render_settings.start_date = str(time.time())
	
	# Track usage of the output serial usage globally to ensure it can be accessed before/after rendering
	# Set it to false ahead of processing to ensure no errors occur (usually only if there's a crash of some sort)
	bpy.context.scene.autosave_render_settings.output_file_serial_used = False
	
	# Filter output file path if enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_path:
		# Save original file path
		bpy.context.scene.autosave_render_settings.output_file_path = filepath = scene.render.filepath
		
		# Check if the serial variable is used
		if '{serial}' in filepath:
			filepath = filepath.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
			bpy.context.scene.autosave_render_settings.output_file_serial_used = True
			
		# Replace scene filepath output with the processed version
		scene.render.filepath = replaceVariables(filepath)
		
	# Filter compositing node file path if turned on in the plugin settings and compositing is enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_nodes and bpy.context.scene.use_nodes:
		# Iterate through Compositor nodes, adding all file output node path and sub-path variables to a dictionary
		node_settings = {}
		for node in bpy.context.scene.node_tree.nodes:
			# Check if the node is a File Output node
			if isinstance(node, bpy.types.CompositorNodeOutputFile):
				# Save the base_path property and the file_slots dictionary entry
				node_settings[node.name] = {
					"base_path": node.base_path,
					"file_slots": {}
				}
				# Replace variables
				if '{serial}' in node.base_path:
					node.base_path = node.base_path.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				node.base_path = replaceVariables(node.base_path)
				
				# Save and then process the sub-path property of each file slot
				for i, slot in enumerate(node.file_slots):
					node_settings[node.name]["file_slots"][i] = {
						"path": slot.path
					}
					# Replace variables
					if '{serial}' in slot.path:
						slot.path = slot.path.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
						bpy.context.scene.autosave_render_settings.output_file_serial_used = True
					slot.path = replaceVariables(slot.path)
					
		# Convert the dictionary to JSON format and save to the plugin preferences for safekeeping while rendering
		bpy.context.scene.autosave_render_settings.output_file_nodes = json.dumps(node_settings)
		
###########################################################################
# Render time remaining estimation function
		
@persistent
def autosave_render_estimate(scene):
	# Save starting frame (before setting active to true, this should only happen once during a sequence)
	if not bpy.context.scene.autosave_render_settings.estimated_render_time_active:
		bpy.context.scene.autosave_render_settings.estimated_render_time_frame = bpy.context.scene.frame_current
	
	# If video sequence is inactive and our current frame is not our starting frame, assume we're rendering a sequence
	if not bpy.context.scene.autosave_render_settings.autosave_video_sequence and bpy.context.scene.autosave_render_settings.estimated_render_time_frame < bpy.context.scene.frame_current:
		bpy.context.scene.autosave_render_settings.autosave_video_sequence = True
	
	# If it's not the last frame, estimate time remaining
	if bpy.context.scene.frame_current < bpy.context.scene.frame_end:
		bpy.context.scene.autosave_render_settings.estimated_render_time_active = True
		# Elapsed time (Current - Render Start)
		render_time = time.time() - float(bpy.context.scene.autosave_render_settings.start_date)
		# Divide by number of frames completed
		render_time /= bpy.context.scene.frame_current - bpy.context.scene.autosave_render_settings.estimated_render_time_frame + 1.0
		# Multiply by number of frames assumed unrendered (does not account for previously completed frames beyond the current frame)
		render_time *= bpy.context.scene.frame_end - bpy.context.scene.frame_current
		# Convert to readable and store
		bpy.context.scene.autosave_render_settings.estimated_render_time_value = secondsToReadable(render_time)
		# print('Estimated Time Remaining: ' + bpy.context.scene.autosave_render_settings.estimated_render_time_value)
	else:
		bpy.context.scene.autosave_render_settings.estimated_render_time_active = False

###########################################################################
# Autosave render function

@persistent
def autosave_render(scene):
	# Set estimated render time active to false (render is complete or canceled, estimate display and FFmpeg check is no longer needed)
	bpy.context.scene.autosave_render_settings.estimated_render_time_active = False
	
	# Calculate elapsed render time
	render_time = round(time.time() - float(bpy.context.scene.autosave_render_settings.start_date), 2)
	
	# Update total render time
	bpy.context.scene.autosave_render_settings.total_render_time = bpy.context.scene.autosave_render_settings.total_render_time + render_time
	
	# Output video files if FFmpeg processing is enabled, the command appears to exist, and the image format output is supported
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_processing and bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_exists and bpy.context.scene.render.image_settings.file_format in FFMPEG_FORMATS and bpy.context.scene.autosave_render_settings.autosave_video_sequence:
		# Create initial command base
		ffmpeg_location = bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_location
		# Create absolute path (strip trailing spaces to clean up output files)
		absolute_path = bpy.path.abspath(scene.render.filepath).rstrip()
		# Create input image glob pattern
		glob_pattern = '-pattern_type glob -i "' + absolute_path + '*' + scene.render.file_extension + '"'
		# Force overwrite and include quotations
		absolute_path = '-y "' + absolute_path + '"'
		# Create floating point FPS value
		fps_float = '-r ' + str(scene.render.fps / scene.render.fps_base)
		
		# ProRes output
		if bpy.context.scene.autosave_render_settings.autosave_video_prores:
			# Set FFmpeg processing to true so the Image View window can display status
			bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = True
			# Set up output path
			output_path = absolute_path
			if len(bpy.context.scene.autosave_render_settings.autosave_video_prores_location) > 1:
				# Replace with custom string
				output_path = bpy.context.scene.autosave_render_settings.autosave_video_prores_location
				# Replace render time variable
				output_path = output_path.replace("{rendertime}", str(render_time) + 's')
				# Check if the serial variable is used
				if '{serial}' in output_path:
					output_path = output_path.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				# Replace the rest of the variables
				output_path = replaceVariables(output_path)
				# Convert relative path into absolute path for Python and CLI compatibility
				output_path = bpy.path.abspath(output_path)
				# Create the project subfolder if it doesn't already exist
				output_dir = sub(r'[^/]*$', "", output_path)
				if not os.path.exists(output_dir):
					os.makedirs(output_dir)
				# Wrap with FFmpeg settings
				output_path = '-y "' + output_path + '"'
			
			# FFmpeg location
			ffmpeg_command = ffmpeg_location
			# Frame rate
			ffmpeg_command += ' ' + fps_float
			# Image sequence pattern
			ffmpeg_command += ' ' + glob_pattern
			# ProRes format
			ffmpeg_command += ' -c:v prores -pix_fmt yuv422p10le'
			# ProRes profile (Proxy, LT, 422 HQ)
			ffmpeg_command += ' -profile:v ' + str(bpy.context.scene.autosave_render_settings.autosave_video_prores_quality)
			# Final output settings
			ffmpeg_command += ' -vendor apl0 -an -sn'
			# Output file path
			ffmpeg_command += ' ' + output_path + '.mov'
			
			# Remove any accidental double spaces
			ffmpeg_command = sub(r'\s{2,}', " ", ffmpeg_command)
			print('ProRes command: ' + ffmpeg_command)
			# Run FFmpeg command
			subprocess.call(ffmpeg_command, shell=True)
		
		# MP4 output
		if bpy.context.scene.autosave_render_settings.autosave_video_mp4:
			# Set FFmpeg processing to true so the Image View window can display status
			bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = True
			# Set up output path
			output_path = absolute_path
			if len(bpy.context.scene.autosave_render_settings.autosave_video_mp4_location) > 1:
				# Replace with custom string
				output_path = bpy.context.scene.autosave_render_settings.autosave_video_mp4_location
				# Replace render time variable
				output_path = output_path.replace("{rendertime}", str(render_time) + 's')
				# Check if the serial variable is used
				if '{serial}' in output_path:
					output_path = output_path.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				# Replace the rest of the variables
				output_path = replaceVariables(output_path)
				# Convert relative path into absolute path for Python and CLI compatibility
				output_path = bpy.path.abspath(output_path)
				# Create the project subfolder if it doesn't already exist
				output_dir = sub(r'[^/]*$', "", output_path)
				if not os.path.exists(output_dir):
					os.makedirs(output_dir)
				# Wrap with FFmpeg settings
				output_path = '-y "' + output_path + '"'
			
			# FFmpeg location
			ffmpeg_command = ffmpeg_location
			# Frame rate
			ffmpeg_command += ' ' + fps_float
			# Image sequence pattern
			ffmpeg_command += ' ' + glob_pattern
			# MP4 format
			ffmpeg_command += ' -c:v libx264 -preset slow'
			# MP4 quality (0-51 from highest to lowest quality)
			ffmpeg_command += ' -crf ' + str(bpy.context.scene.autosave_render_settings.autosave_video_mp4_quality)
			# Final output settings
			ffmpeg_command += ' -pix_fmt yuv420p -movflags rtphint'
			# Output file path
			ffmpeg_command += ' ' + output_path + '.mp4'
			
			# Remove any accidental double or more spaces
			ffmpeg_command = sub(r'\s{2,}', " ", ffmpeg_command)
			print('MP4 command: ' + ffmpeg_command)
			# Run FFmpeg command
			subprocess.call(ffmpeg_command, shell=True)
		
		# Custom output
		if bpy.context.scene.autosave_render_settings.autosave_video_custom:
			# Set FFmpeg processing to true so the Image View window can display status
			bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = True
			# Set up output path
			output_path = absolute_path
			if len(bpy.context.scene.autosave_render_settings.autosave_video_custom_location) > 1:
				# Replace with custom string
				output_path = bpy.context.scene.autosave_render_settings.autosave_video_custom_location
				# Replace render time variable
				output_path = output_path.replace("{rendertime}", str(render_time) + 's')
				# Check if the serial variable is used
				if '{serial}' in output_path:
					output_path = output_path.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				# Replace the rest of the variables
				output_path = replaceVariables(output_path)
				# Convert relative path into absolute path for Python and CLI compatibility
				output_path = bpy.path.abspath(output_path)
				# Create the project subfolder if it doesn't already exist
				output_dir = sub(r'[^/]*$', "", output_path)
				if not os.path.exists(output_dir):
					os.makedirs(output_dir)
				# Wrap with FFmpeg settings
				output_path = '-y "' + output_path + '"'
			
			# FFmpeg location
			ffmpeg_command = ffmpeg_location + ' ' + bpy.context.scene.autosave_render_settings.autosave_video_custom_command
			# Replace variables
			ffmpeg_command = ffmpeg_command.replace("{fps}", fps_float)
			ffmpeg_command = ffmpeg_command.replace("{input}", glob_pattern)
			ffmpeg_command = ffmpeg_command.replace("{output}", output_path)
			
			# Remove any accidental double spaces
			ffmpeg_command = sub(r'\s{2,}', " ", ffmpeg_command)
			print('Custom command: ' + ffmpeg_command)
			# Run FFmpeg command
			subprocess.call(ffmpeg_command, shell=True)
	
	# Increment the output serial number if it was used any output path
	if bpy.context.scene.autosave_render_settings.output_file_serial_used:
		bpy.context.scene.autosave_render_settings.output_file_serial += 1
	
	# Set video sequence status to false
	bpy.context.scene.autosave_render_settings.autosave_video_sequence = False
	bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = False
	
	# Restore unprocessed file path if processing is enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_path and bpy.context.scene.autosave_render_settings.output_file_path:
		scene.render.filepath = bpy.context.scene.autosave_render_settings.output_file_path
	
	# Restore unprocessed node output file path if processing is enabled, compositing is enabled, and a file output node exists with the default node name
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_nodes and bpy.context.scene.use_nodes and len(bpy.context.scene.autosave_render_settings.output_file_nodes) > 2:
		
		# Get the JSON data from the preferences string where it was stashed
		json_data = bpy.context.scene.autosave_render_settings.output_file_nodes
		
		# If the JSON data is not empty, deserialize it and restore the node settings
		if json_data:
			node_settings = json.loads(json_data)
			for node_name, node_data in node_settings.items():
				node = bpy.context.scene.node_tree.nodes.get(node_name)
				if isinstance(node, bpy.types.CompositorNodeOutputFile):
					node.base_path = node_data.get("base_path", node.base_path)
					file_slots_data = node_data.get("file_slots", {})
					for i, slot_data in file_slots_data.items():
						slot = node.file_slots[int(i)]
						if slot:
							slot.path = slot_data.get("path", slot.path)
	
	# Get project name (used by both autosave render and the external log file)
	projectname = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
	
	# Autosave render
	if (bpy.context.scene.autosave_render_settings.enable_autosave_render or bpy.context.preferences.addons['VF_autosaveRender'].preferences.enable_autosave_render_override) and bpy.data.filepath:
		
		# Save original file format settings
		original_format = scene.render.image_settings.file_format
		original_colormode = scene.render.image_settings.color_mode
		original_colordepth = scene.render.image_settings.color_depth
		
		# Set up render output formatting with override
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_format_override:
			file_format = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_format_global
		else:
			file_format = bpy.context.scene.autosave_render_settings.file_format
		
		if file_format == 'SCENE':
			if original_format not in IMAGE_FORMATS:
				print('VF Autosave Render: {} is not an image format. Image not saved.'.format(original_format))
				return {'CANCELLED'}
		elif file_format == 'JPEG':
			scene.render.image_settings.file_format = 'JPEG'
		elif file_format == 'PNG':
			scene.render.image_settings.file_format = 'PNG'
		elif file_format == 'OPEN_EXR':
			scene.render.image_settings.file_format = 'OPEN_EXR'
		extension = scene.render.file_extension
		
		# Get location variable with override and project path replacement
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_override:
			filepath = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_global
		else:
			filepath = bpy.context.scene.autosave_render_settings.file_location
		
		# If the file path contains one or fewer characters, replace it with the project path
		if len(filepath) <= 1:
			filepath = os.path.join(os.path.dirname(bpy.data.filepath), projectname)
			
		# Convert relative path into absolute path for Python compatibility
		filepath = bpy.path.abspath(filepath)
		
		# Process elements that aren't available in the global variable replacement
		# The autosave serial number is separate from the project serial number, and must be handled here before global replacement
		serialUsedGlobal = False
		serialUsed = False
		filepath = filepath.replace("{rendertime}", str(render_time) + 's')
		if '{serial}' in filepath:
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_override:
				filepath = filepath.replace("{serial}", format(bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_serial_global, '04'))
				serialUsedGlobal = True
			else:
				filepath = filepath.replace("{serial}", format(bpy.context.scene.autosave_render_settings.file_serial, '04'))
				serialUsed = True
		
		# Replace global variables in the output name string
		filepath = replaceVariables(filepath)
		
		# Create the project subfolder if it doesn't already exist (otherwise subsequent operations will fail)
		if not os.path.exists(filepath):
			os.makedirs(filepath)
		
		# Get file name type with override
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override:
			file_name_type = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_type_global
		else:
			file_name_type = bpy.context.scene.autosave_render_settings.file_name_type
		
		# Create the output file name string
		if file_name_type == 'SERIAL':
			# Generate dynamic serial number
			# Finds all of the image files that start with projectname in the selected directory
			files = [f for f in os.listdir(filepath)
					if f.startswith(projectname)
					and f.lower().endswith(IMAGE_EXTENSIONS)]
			
			# Searches the file collection and returns the next highest number as a 4 digit string
			def save_number_from_files(files):
				highest = -1
				if files:
					for f in files:
						# find filenames that end with four or more digits
						suffix = findall(r'\d{4,}$', os.path.splitext(f)[0].split(projectname)[-1], multiline)
						if suffix:
							if int(suffix[-1]) > highest:
								highest = int(suffix[-1])
				return format(highest+1, '04')
			
			# Create string with serial number
			filename = '{project}-' + save_number_from_files(files)
		elif file_name_type == 'DATE':
			filename = '{project} {date} {time}'
		elif file_name_type == 'RENDER':
			# Render time is not availble in the global variable replacement becuase it's computed in the above section of code, not universally available
			filename = '{project} {renderengine} ' + str(render_time)
		else:
			# Load custom file name with override
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override:
				filename = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_custom_global
			else:
				filename = bpy.context.scene.autosave_render_settings.file_name_custom
		
		filename = filename.replace("{rendertime}", str(render_time) + 's')
		if '{serial}' in filename:
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override:
				filename = filename.replace("{serial}", format(bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_serial_global, '04'))
				serialUsedGlobal = True
			else:
				filename = filename.replace("{serial}", format(bpy.context.scene.autosave_render_settings.file_serial, '04'))
				serialUsed = True
		
		# Finish local and global serial number updates
		if serialUsedGlobal:
			bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_serial_global += 1
		if serialUsed:
			bpy.context.scene.autosave_render_settings.file_serial += 1
		
		# Replace global variables in the output name string
		filename = replaceVariables(filename)
		
		# Combine file path and file name using system separator, add extension
		filepath = os.path.join(filepath, filename) + extension
		
		# Save image file
		image = bpy.data.images['Render Result']
		if not image:
			print('VF Autosave Render: Render Result not found. Image not saved.')
			return {'CANCELLED'}
		
		# Please note that multilayer EXR files are currently unsupported in the Python API - https://developer.blender.org/T71087
		image.save_render(filepath, scene=None) # Might consider using bpy.context.scene if different compression settings are desired per-scene?
		
		# Restore original user settings for render output
		scene.render.image_settings.file_format = original_format
		scene.render.image_settings.color_mode = original_colormode
		scene.render.image_settings.color_depth = original_colordepth
	
	# Pushover notification
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_enable and len(bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_key) == 30 and len(bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_app) == 30:
		message = bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_message
		message = message.replace("{rendertime}", str(render_time) + 's')
		message = message.replace("{serial}", format(bpy.context.scene.autosave_render_settings.file_serial, '04'))
		message = replaceVariables(message)
		try:
			r = requests.post('https://api.pushover.net/1/messages.json', data = {
				"token": bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_app,
				"user": bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_key,
				"title": "Blender Render Completed",
				"message": message
			})
			if r.status_code == 200:
				print(r.text)
			if r.status_code == 500:
				print('Error in VF Autosave Render: Pushover notification service unavailable')
				print(r.text)
			else:
				print('Error in VF Autosave Render: Pushover URL request failed')
				print(r.text)
		except Exception as exc:
			print(str(exc) + " | Error in VF Autosave Render: failed to send Pushover notification")
	
	# MacOS Siri text-to-speech announcement
	# Re-check Say location just to be extra-sure (otherwise this is only checked when the add-on is first enable)
	bpy.context.preferences.addons[__name__].preferences.check_macos_say_location()
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.macos_say_exists and bpy.context.preferences.addons['VF_autosaveRender'].preferences.macos_say_enable:
		message = bpy.context.preferences.addons['VF_autosaveRender'].preferences.macos_say_message
		message = message.replace("{rendertime}", str(render_time))
		message = message.replace("{serial}", format(bpy.context.scene.autosave_render_settings.file_serial, '04'))
		message = replaceVariables(message)
		os.system('say "' + message + '"')
	
	# Save external log file
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.external_render_time:
		# Log file settings
		logname = bpy.context.preferences.addons['VF_autosaveRender'].preferences.external_log_name
		logname = logname.replace("{project}", projectname)
		logpath = os.path.join(os.path.dirname(bpy.data.filepath), logname) # Limited to locations local to the project file
		logtitle = 'Total Render Time: '
		logtime = 0.00
		
		# Get previous time spent rendering, if log file exists, and convert formatted string into seconds
		if os.path.exists(logpath):
			with open(logpath) as filein:
				logtime = filein.read().replace(logtitle, '')
				logtime = readableToSeconds(logtime)
		# Create log file directory location if it doesn't exist
		elif not os.path.exists(os.path.dirname(logpath)): # Safety net just in case a folder was included in the file name entry
			os.makedirs(os.path.dirname(logpath))
		
		# Add the latest render time
		logtime += float(render_time)
		
		# Convert seconds into formatted string
		logtime = secondsToReadable(logtime)
		
		# Write log file
		with open(logpath, 'w') as fileout:
			fileout.write(logtitle + logtime)
	
	return {'FINISHED'}

###########################################################################
# Variable replacement function for globally accessible variables (serial number must be provided)
# Excludes {rendertime} as it does not exist at the start of rendering

def replaceVariables(string):
	# Get render engine feature sets
	if bpy.context.engine == 'BLENDER_WORKBENCH':
		renderEngine = 'Workbench'
		renderDevice = 'GPU'
		renderSamples = bpy.context.scene.display.render_aa
		renderFeatures = bpy.context.scene.display.shading.light.title().replace("Matcap", "MatCap") + '+' + bpy.context.scene.display.shading.color_type.title()

	elif bpy.context.engine == 'BLENDER_EEVEE':
		renderEngine = 'Eevee'
		renderDevice = 'GPU'
		renderSamples = str(bpy.context.scene.eevee.taa_render_samples) + '+' + str(bpy.context.scene.eevee.sss_samples) + '+' + str(bpy.context.scene.eevee.volumetric_samples)
		renderFeaturesArray = []
		if bpy.context.scene.eevee.use_gtao:
			renderFeaturesArray.append('AO')
		if bpy.context.scene.eevee.use_bloom:
			renderFeaturesArray.append('Bloom')
		if bpy.context.scene.eevee.use_ssr:
			renderFeaturesArray.append('SSR')
		if bpy.context.scene.eevee.use_motion_blur:
			renderFeaturesArray.append('MB')
		renderFeatures = 'None' if len(renderFeaturesArray) == 0 else '+'.join(renderFeaturesArray)

	elif bpy.context.engine == 'CYCLES':
		renderEngine = 'Cycles'
		renderDevice = bpy.context.scene.cycles.device
		# Add compute device type if GPU is enabled
		# if renderDevice == "GPU":
			# renderDevice += '_' + bpy.context.preferences.addons["cycles"].preferences.compute_device_type
		renderSamples = str(round(bpy.context.scene.cycles.adaptive_threshold, 4)) + '+' + str(bpy.context.scene.cycles.samples) + '+' + str(bpy.context.scene.cycles.adaptive_min_samples)
		renderFeatures = str(bpy.context.scene.cycles.max_bounces) + '+' + str(bpy.context.scene.cycles.diffuse_bounces) + '+' + str(bpy.context.scene.cycles.glossy_bounces) + '+' + str(bpy.context.scene.cycles.transmission_bounces) + '+' + str(bpy.context.scene.cycles.volume_bounces) + '+' + str(bpy.context.scene.cycles.transparent_max_bounces)

	elif bpy.context.engine == 'RPR':
		renderEngine = 'ProRender'
		# Compile array of enabled devices
		renderDevicesArray = []
		if bpy.context.preferences.addons["rprblender"].preferences.settings.final_devices.cpu_state:
			renderDevicesArray.append('CPU')
		for gpu in bpy.context.preferences.addons["rprblender"].preferences.settings.final_devices.available_gpu_states:
			if gpu:
				renderDevicesArray.append('GPU')
		renderDevice = 'None' if len(renderDevicesArray) == 0 else '+'.join(renderDevicesArray)
		renderSamples = str(bpy.context.scene.rpr.limits.min_samples) + '+' + str(bpy.context.scene.rpr.limits.max_samples) + '+' + str(round(bpy.context.scene.rpr.limits.noise_threshold, 4))
		renderFeatures = str(bpy.context.scene.rpr.max_ray_depth) + '+' + str(bpy.context.scene.rpr.diffuse_depth) + '+' + str(bpy.context.scene.rpr.glossy_depth) + '+' + str(bpy.context.scene.rpr.refraction_depth) + '+' + str(bpy.context.scene.rpr.glossy_refraction_depth) + '+' + str(bpy.context.scene.rpr.shadow_depth)

	elif bpy.context.engine == 'LUXCORE':
		renderEngine = 'LuxCore'
		renderDevice = 'CPU' if bpy.context.scene.luxcore.config.device == 'CPU' else 'GPU'
		# Samples returns the halt conditions for time, samples, and/or noise threshold
		renderSamples = ''
		if bpy.context.scene.luxcore.halt.use_time:
			renderSamples += str(bpy.context.scene.luxcore.halt.time) + 's'
		if bpy.context.scene.luxcore.halt.use_samples:
			if len(renderSamples) > 0:
				renderSamples += '+'
			renderSamples += str(bpy.context.scene.luxcore.halt.samples)
		if bpy.context.scene.luxcore.halt.use_noise_thresh:
			if len(renderSamples) > 0:
				renderSamples += '+'
			renderSamples += str(bpy.context.scene.luxcore.halt.noise_thresh) + '+' + str(bpy.context.scene.luxcore.halt.noise_thresh_warmup) + '+' + str(bpy.context.scene.luxcore.halt.noise_thresh_step)
		# Features include the number of paths or bounces (depending on engine selected) and denoising if enabled
		if bpy.context.scene.luxcore.config.engine == 'PATH':
			renderEngine += '-Path'
			renderFeatures = str(bpy.context.scene.luxcore.config.path.depth_total) + '+' + str(bpy.context.scene.luxcore.config.path.depth_diffuse) + '+' + str(bpy.context.scene.luxcore.config.path.depth_glossy) + '+' + str(bpy.context.scene.luxcore.config.path.depth_specular)
		else:
			renderEngine += '-Bidir'
			renderFeatures = str(bpy.context.scene.luxcore.config.bidir_path_maxdepth) + '+' + str(bpy.context.scene.luxcore.config.bidir_light_maxdepth)
		if bpy.context.scene.luxcore.denoiser.enabled:
			renderFeatures += '+' + str(bpy.context.scene.luxcore.denoiser.type)

	else:
		renderEngine = bpy.context.engine
		renderDevice = 'unknown'
		renderSamples = 'unknown'
		renderFeatures = 'unknown'
	
	# Get conditional project variables
	projectItem = projectMaterial = projectNode = 'None'
	if bpy.context.view_layer.objects.active:
		# Set active object name
		projectItem = bpy.context.view_layer.objects.active.name
		if bpy.context.view_layer.objects.active.active_material:
			# Set active material slot name
			projectMaterial = bpy.context.view_layer.objects.active.active_material.name
			if bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active:
				# Set image name to the Batch Render Target if active and available
				if bpy.context.scene.autosave_render_settings.batch_active and bpy.context.scene.autosave_render_settings.batch_type == 'imgs' and bpy.data.materials.get(bpy.context.scene.autosave_render_settings.batch_images_material) and bpy.data.materials[bpy.context.scene.autosave_render_settings.batch_images_material].node_tree.nodes.get(bpy.context.scene.autosave_render_settings.batch_images_node):
					projectNode = bpy.data.materials[bpy.context.scene.autosave_render_settings.batch_images_material].node_tree.nodes.get(bpy.context.scene.autosave_render_settings.batch_images_node).image.name
				# Set active node name or image name if available
				elif bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.type == 'TEX_IMAGE' and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.image.has_data:
					projectNode = bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.image.name
				else:
					projectNode = bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.name
				# Remove file extension (this could be unhelpful if we need to compare renders with a .psd versus .jpg)
				projectNode = sub(r'\.\w{3,4}$', '', projectNode)
	
	# Using "replace" instead of "format" because format fails ungracefully when an exact match isn't found
	# Project variables
	string = string.replace("{project}", os.path.splitext(os.path.basename(bpy.data.filepath))[0])
	string = string.replace("{scene}", bpy.context.scene.name)
	string = string.replace("{collection}", bpy.context.collection.name)
	string = string.replace("{camera}", bpy.context.scene.camera.name)
	string = string.replace("{item}", projectItem)
	string = string.replace("{material}", projectMaterial)
	string = string.replace("{node}", projectNode)
	# Rendering variables
	string = string.replace("{renderengine}", renderEngine)
	string = string.replace("{device}", renderDevice)
	string = string.replace("{samples}", renderSamples)
	string = string.replace("{features}", renderFeatures)
		# {rendertime} must be handled exclusively in the post-render function
	# System variables
	string = string.replace("{host}", platform.node().split('.')[0])
	string = string.replace("{platform}", platform.platform())
	string = string.replace("{version}", bpy.app.version_string + '-' + bpy.app.version_cycle)
	# Identifier variables
	string = string.replace("{date}", datetime.datetime.now().strftime('%Y-%m-%d'))
	string = string.replace("{year}", "{y}") # Alternative variable
	string = string.replace("{y}", datetime.datetime.now().strftime('%Y'))
	string = string.replace("{month}", "{m}") # Alternative variable
	string = string.replace("{m}", datetime.datetime.now().strftime('%m'))
	string = string.replace("{day}", "{d}") # Alternative variable
	string = string.replace("{d}", datetime.datetime.now().strftime('%d'))
	string = string.replace("{time}", datetime.datetime.now().strftime('%H-%M-%S'))
	string = string.replace("{hour}", "{H}") # Alternative variable
	string = string.replace("{H}", datetime.datetime.now().strftime('%H'))
	string = string.replace("{minute}", "{M}") # Alternative variable
	string = string.replace("{M}", datetime.datetime.now().strftime('%M'))
	string = string.replace("{second}", "{S}") # Alternative variable
	string = string.replace("{S}", datetime.datetime.now().strftime('%S'))
		# the {serial} variable is handled elsewhere to account for separate autosave and output numbering
	string = string.replace("{frame}", format(bpy.context.scene.frame_current, '04'))
	return string

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
# Global user preferences and UI rendering class

class AutosaveRenderPreferences(bpy.types.AddonPreferences):
	bl_idname = __name__

	# Global Variables
	filter_output_file_path: bpy.props.BoolProperty(
		name='Render Output Variables',
		description='Implements most of the same keywords used in the custom naming scheme in the Output directory',
		default=True)
	filter_output_file_nodes: bpy.props.BoolProperty(
		name='File Output Node Variables',
		description='Implements most of the same keywords used in the custom naming scheme in Compositing tab "File Output" nodes',
		default=True)
	remaining_render_time: bpy.props.BoolProperty(
		name="Estimate Remaining Render Time",
		description='Adds estimated remaining render time display to the image editor menu',
		default=True)
	show_total_render_time: bpy.props.BoolProperty(
		name="Show Project Render Time",
		description='Displays the total time spent rendering a project in the output panel',
		default=True)
	external_render_time: bpy.props.BoolProperty(
		name="Save External Render Time Log",
		description='Saves the total time spent rendering to an external log file',
		default=False)
	external_log_name: bpy.props.StringProperty(
		name="File Name",
		description="Log file name; use {project} for per-project tracking, remove it for per-directory tracking",
		default="{project}-TotalRenderTime.txt",
		maxlen=4096)
	
	# Override individual project autosave location and file name settings
	enable_autosave_render_override: bpy.props.BoolProperty(
		name="Always Autosave",
		description="Globally enables autosaving renders regardless of individual project settings",
		default=False)
	
	file_location_override: bpy.props.BoolProperty(
		name="File Location",
		description='Global override for the per-project directory setting',
		default=False)
	file_location_global: bpy.props.StringProperty(
		name="Global File Location",
		description="Leave a single forward slash to auto generate folders alongside project files",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH")
	
	file_name_override: bpy.props.BoolProperty(
		name="File Name",
		description='Global override for the per-project autosave file name setting',
		default=False)
	file_name_type_global: bpy.props.EnumProperty(
		name='Global File Name',
		description='Autosaves files with the project name and serial number, project name and date, or custom naming pattern',
		items=[
			('SERIAL', 'Project Name + Serial Number', 'Save files with a sequential serial number'),
			('DATE', 'Project Name + Date & Time', 'Save files with the local date and time'),
			('RENDER', 'Project Name + Render Engine + Render Time', 'Save files with the render engine and render time'),
			('CUSTOM', 'Custom String', 'Save files with a custom string format'),
			],
		default='SERIAL')
	file_name_custom_global: bpy.props.StringProperty(
		name="Global Custom String",
		description="Format a custom string using the variables listed below",
		default="{project}-{serial}",
		maxlen=4096)
	file_serial_global: bpy.props.IntProperty(
		name="Global Serial Number",
		description="Current serial number, automatically increments with every render (must be manually updated when installing a plugin update)")
	
	file_format_override: bpy.props.BoolProperty(
		name="File Format",
		description='Global override for the per-project autosave file format setting',
		default=False)
	file_format_global: bpy.props.EnumProperty(
		name='Global File Format',
		description='Image format used for the automatically saved render files',
		items=[
			('SCENE', 'Project Setting', 'Same format as set in output panel'),
			('PNG', 'PNG', 'Save as png'),
			('JPEG', 'JPEG', 'Save as jpeg'),
			('OPEN_EXR', 'OpenEXR', 'Save as exr'),
			],
		default='PNG')
	
	# FFMPEG output processing
	ffmpeg_processing: bpy.props.BoolProperty(
		name='Enable Autosave Video',
		description='Enables FFmpeg image sequence compilation options in the Output panel',
		default=True)
	ffmpeg_location: bpy.props.StringProperty(
		name="FFmpeg location",
		description="System location where the the FFmpeg command line interface is installed",
		default="/",
		maxlen=4096,
		update=lambda self, context: self.check_ffmpeg_location())
	ffmpeg_location_previous: bpy.props.StringProperty(default="")
	ffmpeg_exists: bpy.props.BoolProperty(
		name="FFmpeg exists",
		description='Stores the existence of FFmpeg at the defined system location',
		default=False)
	
	# Validate the ffmpeg location string on value change and plugin registration
	def check_ffmpeg_location(self):
		# Ensure it points at ffmpeg
		if not self.ffmpeg_location.endswith('ffmpeg'):
			self.ffmpeg_location = self.ffmpeg_location + 'ffmpeg'
		# Test if it's a valid path and replace with valid path if such exists
		if self.ffmpeg_location != self.ffmpeg_location_previous:
			if which(self.ffmpeg_location) is None:
				if which("ffmpeg") is None:
					self.ffmpeg_exists = False
				else:
					self.ffmpeg_location = which("ffmpeg")
					self.ffmpeg_exists = True
			else:
				self.ffmpeg_exists = True
			self.ffmpeg_location_previous = self.ffmpeg_location
	
	# Render Complete Notifications
	# Pushover app notifications
	pushover_enable: bpy.props.BoolProperty(
		name='Pushover Notification',
		description='Enable Pushover mobile device push notifications (requires non-subscription app and user account https://pushover.net/)',
		default=False)
	pushover_key: bpy.props.StringProperty(
		name="Pushover User Key",
		description="Pushover user key, available after setting up a user account",
		default="EnterUserKeyHere",
		maxlen=64)
	pushover_app: bpy.props.StringProperty(
		name="Pushover App Token",
		description="Pushover application token, available after setting up a custom application",
		default="EnterAppTokenHere",
		maxlen=64)
	pushover_message: bpy.props.StringProperty(
		name="Pushover Message",
		description="Message that will be sent to Pushover devices",
		default="\"{project}\" rendering completed on {host}",
		maxlen=2048)
	
	# MacOS Siri text-to-speech announcement
	macos_say_enable: bpy.props.BoolProperty(
		name='Siri Announcement',
		description='Enable MacOS Siri text-to-speech announcements',
		default=False)
	macos_say_exists: bpy.props.BoolProperty(
		name="MacOS Say exists",
		description='Stores the existence of MacOS Say',
		default=False)
	macos_say_message: bpy.props.StringProperty(
		name="Siri Message",
		description="Message that Siri will read out loud",
		default="\"{project}\" rendering completed in {rendertime} seconds",
		maxlen=2048)
	
	# Validate the MacOS Say location on plugin registration
	def check_macos_say_location(self):
		# Test if it's a valid path
		self.macos_say_exists = False if which('say') is None else True
	
	
	
	# User Interface
	def draw(self, context):
		layout = self.layout
	
	# Preferences:
		grid0 = layout.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		grid0.prop(self, "filter_output_file_path")
		grid0.prop(self, "filter_output_file_nodes")
		
	# Render Time:
		layout.separator()
		layout.label(text="Render Time:")
		
		grid1 = layout.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		grid1.prop(self, "show_total_render_time")
		input = grid1.row()
		if not self.show_total_render_time:
			input.active = False
			input.enabled = False
		input.prop(context.scene.autosave_render_settings, 'total_render_time')
		
		grid1.prop(self, "external_render_time")
		input1 = grid1.row()
		if not self.external_render_time:
			input1.active = False
			input1.enabled = False
		input1.prop(self, "external_log_name", text='')
		
		grid1.prop(self, "remaining_render_time")
		
	# Global Overrides:
		layout.separator()
		layout.label(text="Global Autosave Overrides:")
		
		grid2 = layout.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		grid2.prop(self, "enable_autosave_render_override")
		grid2.separator()

		# Disable everything if autosave override isn't engaged
		group = layout.column()
		if not self.enable_autosave_render_override:
			group.active = False
			group.enabled = False
		
		ops = group.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
		ops.rendertime = True
		grid2 = group.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		grid2.separator()
		if not ((self.file_name_override and self.file_name_type_global == 'CUSTOM' and '{serial}' in self.file_name_custom_global) or (self.file_location_override and '{serial}' in self.file_location_global)):
			grid2.active = False
			grid2.enabled = False
		grid2.prop(self, "file_serial_global", text="")
		
		grid2 = group.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		toggle = grid2.column(align=True)
		toggle.prop(self, "file_location_override")
		input = grid2.column(align=True)
		if not self.file_location_override:
			input.active = False
			input.enabled = False
		input.prop(self, "file_location_global", text='')
		
		grid2 = group.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		toggle = grid2.column()
		toggle.prop(self, "file_name_override")
		col = grid2.column()
		if not self.file_name_override:
			col.active = False
			col.enabled = False
		input = col.row()
		input.prop(self, "file_name_type_global", text='', icon='FILE_TEXT')
		input = col.row()
		if (self.file_name_type_global == 'CUSTOM'):
#			input.active = False
#			input.enabled = False
			input.prop(self, "file_name_custom_global", text='')
		
		grid2.prop(self, "file_format_override")
		input = grid2.column()
		if not self.file_format_override:
			input.active = False
			input.enabled = False
		input.prop(self, "file_format_global", text='', icon='FILE_IMAGE')
		if self.file_format_override and self.file_format_global == 'SCENE' and bpy.context.scene.render.image_settings.file_format == 'OPEN_EXR_MULTILAYER':
			error = group.box()
			error.label(text="Python API can only save single layer EXR files")
			error.label(text="Report: https://developer.blender.org/T71087")
			
	# FFmpeg Sequencing
		layout.separator()
		layout.label(text="Autosave image sequences as videos:")
		
		# Enable
		grid3 = layout.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		grid3.prop(self, "ffmpeg_processing")
		
		# Location input field
		input = grid3.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		if not self.ffmpeg_processing:
			input.active = False
			input.enabled = False
		input.prop(self, "ffmpeg_location", text="")
		
		# Location exists success/fail
		if self.ffmpeg_exists:
			input.label(text="✔︎ installed")
		else:
			input.label(text="✘ missing")
		
	# Notifications
		layout.separator()
		layout.label(text="Render Complete Notifications:")
		
		# Pushover notifications
		layout.prop(self, "pushover_enable")
		column = layout.column(align=True)
		row = column.row(align=True)
		if not self.pushover_enable:
			column.active = False
			column.enabled = False
		row.prop(self, "pushover_key", text="")
		row.prop(self, "pushover_app", text="")
		column.prop(self, "pushover_message", text="")
		
		# Apple MacOS Siri text-to-speech announcement
		if self.macos_say_exists:
			layout.prop(self, "macos_say_enable")
			input = layout.row()
			if not self.macos_say_enable:
				input.active = False
				input.enabled = False
			input.prop(self, "macos_say_message", text='')



###########################################################################
# Local project settings

class AutosaveRenderSettings(bpy.types.PropertyGroup):
	enable_autosave_render: bpy.props.BoolProperty(
		name="Enable/disable automatic saving of rendered images",
		description="Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
		default=True)
	file_location: bpy.props.StringProperty(
		name="File Location",
		description="Leave a single forward slash to auto generate folders alongside project files",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH")
	file_name_type: bpy.props.EnumProperty(
		name='File Name',
		description='Autosaves files with the project name and serial number, project name and date, or custom naming pattern',
		items=[
			('SERIAL', 'Project Name + Serial Number', 'Save files with a sequential serial number'),
			('DATE', 'Project Name + Date & Time', 'Save files with the local date and time'),
			('RENDER', 'Project Name + Render Engine + Render Time', 'Save files with the render engine and render time'),
			('CUSTOM', 'Custom String', 'Save files with a custom string format'),
			],
		default='SERIAL')
	file_name_custom: bpy.props.StringProperty(
		name="Custom String",
		description="Format a custom string using the variables listed below",
		default="{project}-{serial}-{renderengine}-{rendertime}",
		maxlen=4096)
	file_serial: bpy.props.IntProperty(
		name="Serial Number",
		description="Current serial number, automatically increments with every render")
	file_format: bpy.props.EnumProperty(
		name='File Format',
		description='Image format used for the automatically saved render files',
		items=[
			('SCENE', 'Project Setting', 'Same format as set in output panel'),
			('PNG', 'PNG', 'Save as png'),
			('JPEG', 'JPEG', 'Save as jpeg'),
			('OPEN_EXR', 'OpenEXR', 'Save as exr'),
			],
		default='JPEG')

	# Variables for render time calculation
	start_date: bpy.props.StringProperty(
		name="Render Start Date",
		description="Stores the date when rendering started in seconds as a string",
		default="")
	total_render_time: bpy.props.FloatProperty(
		name="Total Render Time",
		description="Stores the total time spent rendering in seconds",
		default=0)

	# Variables for render time estimation
	estimated_render_time_active: bpy.props.BoolProperty(
		name="Render Active",
		description="Indicates if rendering is currently active",
		default=False)
	estimated_render_time_frame: bpy.props.IntProperty(
		name="Starting frame",
		description="Saves the starting frame when render begins (helps correctly estimate partial renders)",
		default=0)
	estimated_render_time_value: bpy.props.StringProperty(
		name="Estimated Render Time",
		description="Stores the estimated time remaining to render",
		default="0:00:00.00")

	# Variables for output file path processing
	output_file_path: bpy.props.StringProperty(
		name="Original Render Path",
		description="Stores the original render path as a string to allow for successful restoration after rendering completes",
		default="")
	output_file_nodes: bpy.props.StringProperty(
		name="Original Node Path",
		description="Stores the original node path as a string to allow for successful restoration after rendering completes",
		default="")
	output_file_serial: bpy.props.IntProperty(
		name="Serial Number",
		description="Current serial number, automatically increments with every render")
	output_file_serial_used: bpy.props.BoolProperty(
		name="Output Serial Number Used",
		description="Indicates if any of the output modules use the {serial} variable",
		default=False)
	
	# FFmpeg image sequence compilation
	autosave_video_sequence: bpy.props.BoolProperty(
		name="Sequence Active",
		description="Indicates if a sequence is being rendering to ensure FFmpeg is enabled only when more than one frame has been rendered",
		default=False)
	autosave_video_sequence_processing: bpy.props.BoolProperty(
		name="Sequence Processing",
		description="Indicates if sequence processing is currently active",
		default=False)
	
	autosave_video_prores: bpy.props.BoolProperty(
		name="Enable ProRes Output",
		description="Automatically compiles completed image sequences into a ProRes compressed .mov file",
		default=False)
	autosave_video_prores_quality: bpy.props.EnumProperty(
		name='ProRes Quality',
		description='Video codec used',
		items=[
			('0', 'Proxy', 'ProResProxy'),
			('1', 'LT', 'ProResLT'),
			('2', '422', 'ProRes422'),
			('3', 'HQ', 'ProRes422HQ'),
			],
		default='3')
	autosave_video_prores_location: bpy.props.StringProperty(
		name="Custom File Location",
		description="Set ProRes file output location and name, use single forward slash to save alongside image sequence",
		default="//../Renders/{project}",
		maxlen=4096,
		subtype="DIR_PATH")
	
	autosave_video_mp4: bpy.props.BoolProperty(
		name="Enable MP4 Output",
		description="Automatically compiles completed image sequences into an H.264 compressed .mp4 file",
		default=False)
	autosave_video_mp4_quality: bpy.props.IntProperty(
		name="Compression Level",
		description="CRF value where 0 is uncompressed and 51 is the lowest quality possible; 23 is the FFmpeg default but 18 produces better results (closer to visually lossless)",
		default=18,
		step=2,
		soft_min=2,
		soft_max=48,
		min=0,
		max=51)
	autosave_video_mp4_location: bpy.props.StringProperty(
		name="Custom File Location",
		description="Set MP4 file output location and name, use single forward slash to save alongside image sequence",
		default="//../Previews/{project}",
		maxlen=4096,
		subtype="DIR_PATH")
	
	autosave_video_custom: bpy.props.BoolProperty(
		name="Enable Custom Output",
		description="Automatically compiles completed image sequences using a custom FFmpeg string",
		default=False)
	autosave_video_custom_command: bpy.props.StringProperty(
		name="Custom FFmpeg Command",
		description="Custom FFmpeg command line string; {input} {fps} {output} variables must be included, but the command path is automatically prepended",
		default='{fps} {input} -vf scale=-2:1080 -c:v libx264 -preset medium -crf 10 -pix_fmt yuv420p -movflags +rtphint -movflags +faststart {output}_1080p.mp4',
				#{fps} {input} -c:v hevc_videotoolbox -pix_fmt bgra -b:v 1M -alpha_quality 1 -allow_sw 1 -vtag hvc1 {output}_alpha.mov
				#{fps} {input} -c:v hevc_videotoolbox -require_sw 1 -allow_sw 1 -alpha_quality 1.0 -vtag hvc1 {output}_alpha.mov
				#{fps} {input} -pix_fmt yuva420p {output}_alpha.webm
				#{fps} {input} -c:v libvpx -pix_fmt yuva420p -crf 16 -b:v 1M -auto-alt-ref 0 {output}_alpha.webm
		maxlen=4096)
	autosave_video_custom_location: bpy.props.StringProperty(
		name="Custom File Location",
		description="Set custom command file output location and name, use single forward slash to save alongside image sequence",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH")
	
	# Batch rendering options
	batch_active: bpy.props.BoolProperty(
		name="Batch Rendering Active",
		description="Tracks status of batch rendering",
		default=False)
	batch_type: bpy.props.EnumProperty(
		name='Batch Type',
		description='Choose the batch rendering system',
		items=[
			('cams', 'Cameras', 'Batch render all specified cameras'),
			('cols', 'Collections', 'Batch render all specified collections'),
			('itms', 'Items', 'Batch render all specified items'),
			(None),
			('imgs', 'Images', 'Batch render using images from specified folder'),
			],
		default='imgs')
	batch_range: bpy.props.EnumProperty(
		name='Range',
		description='Batch render single frame or full timeline sequence',
		items=[
			('still', 'Still', 'Batch render single frame for each element'),
			('sequence', 'Sequence', 'Batch render timeline range for each element')
			],
		default='sequence')
	# Batch cameras
	# Batch collections
	# Batch items
	# Batch images
	batch_images_location: bpy.props.StringProperty(
		name="Source Folder",
		description="Source folder of images to be used in batch rendering",
		default="",
		maxlen=4096,
		subtype="DIR_PATH")
	batch_images_material: bpy.props.StringProperty(
		name="Target Material",
		description='Target material for batch rendering images',
		default='',
		maxlen=4096)
	batch_images_node: bpy.props.StringProperty(
		name="Target Node",
		description='Target node for batch rendering images',
		default='',
		maxlen=4096)



###########################################################################
# Output Properties panel UI rendering classes

class RENDER_PT_autosave_video(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Autosave Video"
	bl_parent_id = "RENDER_PT_output"

	@classmethod
	def poll(cls, context):
		return (
			# Check if FFmpeg processing is enabled
			bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_processing
			# Check if the FFmpeg appears to be valid
			and bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_exists
			# Check if the output format is supported by FFmpeg
			and bpy.context.scene.render.image_settings.file_format in FFMPEG_FORMATS
		)
	
	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		
		# Variable list popup button
		ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
		ops.rendertime = True
		
		# Display serial number if used in any enabled FFmpeg output paths
		paths = ''
		if bpy.context.scene.autosave_render_settings.autosave_video_prores:
			paths += bpy.context.scene.autosave_render_settings.autosave_video_prores_location
		if bpy.context.scene.autosave_render_settings.autosave_video_mp4:
			paths += bpy.context.scene.autosave_render_settings.autosave_video_mp4_location
		if bpy.context.scene.autosave_render_settings.autosave_video_custom:
			paths += bpy.context.scene.autosave_render_settings.autosave_video_custom_location
		input = layout.row()
		input.use_property_split = True
		if not '{serial}' in paths:
			input.active = False
			input.enabled = False
		input.prop(context.scene.autosave_render_settings, 'output_file_serial')
		
		# ProRes alternate UI
		layout.separator()
		row1 = layout.row()
		row1a = row1.row()
		row1a.scale_x = 0.8333
		row1a.prop(context.scene.autosave_render_settings, 'autosave_video_prores', text='Create ProRes')
		row1b = row1.row(align=True)
		row1b.scale_x = 0.25
		row1b.prop(context.scene.autosave_render_settings, 'autosave_video_prores_quality', expand=True)
		row2 = layout.row()
		row2.prop(context.scene.autosave_render_settings, 'autosave_video_prores_location', text='')
		if not bpy.context.scene.autosave_render_settings.autosave_video_prores:
			row1b.active = False
			row1b.enabled = False
			row2.active = False
			row2.enabled = False
		
		# MP4 alternate UI
		layout.separator()
		row1 = layout.row()
		row1a = row1.row()
		row1a.scale_x = 0.8333
		row1a.prop(context.scene.autosave_render_settings, 'autosave_video_mp4', text='Create MP4')
		row1b = row1.row()
		row1b.prop(context.scene.autosave_render_settings, 'autosave_video_mp4_quality', slider=True)
		row2 = layout.row()
		row2.prop(context.scene.autosave_render_settings, 'autosave_video_mp4_location', text='')
		if not bpy.context.scene.autosave_render_settings.autosave_video_mp4:
			row1b.active = False
			row1b.enabled = False
			row2.active = False
			row2.enabled = False
		
		# Custom alternate UI
		layout.separator()
		row1 = layout.row()
		row1a = row1.row()
		row1a.scale_x = 0.8333
		row1a.prop(context.scene.autosave_render_settings, 'autosave_video_custom', text='Create Custom')
		row1b = row1.row()
		row1b.prop(context.scene.autosave_render_settings, 'autosave_video_custom_command', text='')
		row2 = layout.row()
		row2.prop(context.scene.autosave_render_settings, 'autosave_video_custom_location', text='')
		if not bpy.context.scene.autosave_render_settings.autosave_video_custom:
			row1b.active = False
			row1b.enabled = False
			row2.active = False
			row2.enabled = False
		
class RENDER_PT_autosave_render(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Autosave Render"
	bl_parent_id = "RENDER_PT_output"
	
	@classmethod
	def poll(cls, context):
		return True
	
	def draw_header(self, context):
		if not bpy.context.preferences.addons['VF_autosaveRender'].preferences.enable_autosave_render_override:
			self.layout.prop(context.scene.autosave_render_settings, 'enable_autosave_render', text='')
	
	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		layout.use_property_split = True
		
		# Disable inputs if Autosave is disabled
		if not bpy.context.scene.autosave_render_settings.enable_autosave_render and not bpy.context.preferences.addons['VF_autosaveRender'].preferences.enable_autosave_render_override:
			layout.active = False
			layout.enabled = False
		
		# Variable list popup button
		ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
		ops.rendertime = True
		
		# Local project serial number
		# Global serial number is listed inline with the path or file override, if used
		input = layout.row()
		input.use_property_split = True
		if not (('{serial}' in bpy.context.scene.autosave_render_settings.file_location and not bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_override) or (bpy.context.scene.autosave_render_settings.file_name_type == 'CUSTOM' and '{serial}' in bpy.context.scene.autosave_render_settings.file_name_custom and not bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override)):
			input.active = False
			input.enabled = False
		input.prop(context.scene.autosave_render_settings, 'file_serial')
		
		# File location with global override
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_override:
			override = layout.row()
			override.use_property_split = True
			override.active = False
			override.prop(bpy.context.preferences.addons['VF_autosaveRender'].preferences, 'file_location_global')
			if '{serial}' in bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_global:
				override.prop(bpy.context.preferences.addons['VF_autosaveRender'].preferences, "file_serial_global", text="")
		else:
			layout.use_property_split = False
			layout.prop(context.scene.autosave_render_settings, 'file_location', text="")
			layout.use_property_split = True
		
		# File name with global override
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override:
			override = layout.row()
			override.active = False
			override.prop(bpy.context.preferences.addons['VF_autosaveRender'].preferences, 'file_name_type_global', icon='FILE_TEXT')
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override and bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_type_global == 'CUSTOM':
				override.prop(bpy.context.preferences.addons['VF_autosaveRender'].preferences, "file_name_custom_global", text='')
				if '{serial}' in bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_custom_global:
					override.prop(bpy.context.preferences.addons['VF_autosaveRender'].preferences, "file_serial_global", text="")
		else:
			layout.prop(context.scene.autosave_render_settings, 'file_name_type', icon='FILE_TEXT')
			if bpy.context.scene.autosave_render_settings.file_name_type == 'CUSTOM':
				layout.prop(context.scene.autosave_render_settings, 'file_name_custom')
		
		# File format with global override
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_format_override:
			override = layout.row()
			override.active = False
			override.prop(bpy.context.preferences.addons['VF_autosaveRender'].preferences, 'file_format_global', icon='FILE_IMAGE')
		else:
			layout.prop(context.scene.autosave_render_settings, 'file_format', icon='FILE_IMAGE')
			
		# Multilayer EXR warning
		if bpy.context.scene.render.image_settings.file_format == 'OPEN_EXR_MULTILAYER' and (bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_format_global == 'SCENE' and bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_format_override or bpy.context.scene.autosave_render_settings.file_format == 'SCENE' and not bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_format_override):
			error = layout.box()
			error.label(text="Python API can only save single layer EXR files")
			error.label(text="Report: https://developer.blender.org/T71087")



###########################################################################
# Variable info popup and serial number UI

# Popup panel
class AutosaveRenderVariablePopup(bpy.types.Operator):
	"""List of the available variables"""
	bl_label = "Variable List"
	bl_idname = "vf.autosave_render_variable_popup"
	bl_options = {'REGISTER', 'INTERNAL'}

	rendertime: bpy.props.BoolProperty()

	@classmethod
	def poll(cls, context):
		return True

	def execute(self, context):
		self.report({'INFO'}, "YES")
		return {'FINISHED'}

	def invoke(self, context, event):
		return context.window_manager.invoke_popup(self, width=380)

	def draw(self, context):
		layout = self.layout
		grid = self.layout.grid_flow(columns = 4, even_columns = True, even_rows = True)
		for item in variableArray:
			# Display headers
			if item.startswith('title,'):
				x = item.split(',')
				col = grid.column()
				col.label(text = x[1], icon = x[2])
			# Display list elements
			elif item != "{rendertime}" or self.rendertime:
#				col.label(text = item)
				if ',' in item:
					subrow = col.row(align = True)
					for subitem in item.split(','):
						ops = subrow.operator(AutosaveRenderVariableCopy.bl_idname, text = subitem, emboss = False)
						ops.string = subitem
				else:
					ops = col.operator(AutosaveRenderVariableCopy.bl_idname, text = item, emboss = False)
					ops.string = item
		layout.label(text = 'Click a variable to copy it to the clipboard', icon = "COPYDOWN")

# Copy string to clipboard
class AutosaveRenderVariableCopy(bpy.types.Operator):
	"""Copy variable to the clipboard"""
	bl_label = "Copy to clipboard"
	bl_idname = "vf.autosave_render_variable_copy"
	bl_options = {'REGISTER', 'INTERNAL'}
	
	string: bpy.props.StringProperty()
	
	def execute(self, context):
		context.window_manager.clipboard = self.string
		return {'FINISHED'}

# Render output UI
def RENDER_PT_output_path_variable_list(self, context):
	if not (False) and bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_path:
		# UI layout for Scene Output
		layout = self.layout
		ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF") # LINENUMBERS_OFF, THREE_DOTS, SHORTDISPLAY, ALIGN_JUSTIFY
		ops.rendertime = False
		layout.use_property_decorate = False
		layout.use_property_split = True
		input = layout.row()
		if not '{serial}' in bpy.context.scene.render.filepath:
			input.active = False
			input.enabled = False
		input.prop(context.scene.autosave_render_settings, 'output_file_serial')

# Node output UI
def NODE_PT_output_path_variable_list(self, context):
	if not (False) and bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_nodes:
		active_node = bpy.context.scene.node_tree.nodes.active
		if isinstance(active_node, bpy.types.CompositorNodeOutputFile):
			# Get file path and all output file names from the current active node
			paths = [bpy.context.scene.node_tree.nodes.active.base_path]
			for slot in bpy.context.scene.node_tree.nodes.active.file_slots:
				paths.append(slot.path)
			paths = ''.join(paths)
			
			# UI layout for Node Properties
			layout = self.layout
			layout.use_property_decorate = False
			layout.use_property_split = True
			ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
			ops.rendertime = False
			input = layout.row()
			if not '{serial}' in paths:
				input.active = False
				input.enabled = False
			input.prop(context.scene.autosave_render_settings, 'output_file_serial')
			layout.use_property_split = False # Base path interface doesn't specify false, it assumes it, so the UI gets screwed up if we don't reset here

###########################################################################
# Display render time in the Render panel

def RENDER_PT_total_render_time_display(self, context):
	if not (False) and bpy.context.preferences.addons['VF_autosaveRender'].preferences.show_total_render_time:
		layout = self.layout
#		layout.use_property_decorate = False
#		layout.use_property_split = True
		box = layout.box()
		box.label(text="Total time spent rendering: "+secondsToReadable(bpy.context.scene.autosave_render_settings.total_render_time))

###########################################################################
# Display feedback in the Image viewer (primarily during rendering)

def image_viewer_feedback_display(self, context):
	# Estimated render time remaining
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.remaining_render_time and bpy.context.scene.autosave_render_settings.estimated_render_time_active:
		self.layout.separator()
		box = self.layout.box()
		box.label(text="  Estimated Time Remaining: " + bpy.context.scene.autosave_render_settings.estimated_render_time_value + " ")
	if bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing:
		self.layout.separator()
		box = self.layout.box()
		box.label(text="  FFmpeg Image Sequence Processing... ")



###########################################################################
# Set material and node for Batch Render feature

class VF_autosave_render_batch_assign_image_target(bpy.types.Operator):
	bl_idname = 'render.vf_autosave_render_batch_assign_image_target'
	bl_label = 'Assign image target'
	bl_description = "Assign active node in material as target for batch rendering images"
	bl_space_type = "NODE_EDITOR"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context):
		return (
			bpy.context.view_layer.objects.active
			and bpy.context.view_layer.objects.active.active_material
			and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active
			and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.type == 'TEX_IMAGE'
		)

	def execute(self, context):
		# Assign active material from active object
		context.scene.autosave_render_settings.batch_images_material = context.view_layer.objects.active.active_material.name
		# Assign active node from active material from active object
		context.scene.autosave_render_settings.batch_images_node = context.view_layer.objects.active.active_material.node_tree.nodes.active.name
		return {'FINISHED'}

###########################################################################
# Begin Batch Render

class VF_autosave_render_batch(bpy.types.Operator):
	bl_idname = 'render.vf_autosave_render_batch'
	bl_label = 'Begin Batch Render'
	bl_description = "Batch render specified elements"
	bl_space_type = "VIEW_3D"
#	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context):
		return ( True )
	
	def invoke(self, context, event):
			return context.window_manager.invoke_props_dialog(self)
	
	def draw(self, context):
		try:
			layout = self.layout
#			layout.operator_context = 'INVOKE_DEFAULT' # 'INVOKE_AREA'
			layout.label(text="Blender will be unresponsive while processing, proceed?")
		except Exception as exc:
			print(str(exc) + ' | Error in VF Autosave Render + Output Variables: Begin Batch Render confirmation header')
	
	def execute(self, context):
		context.scene.autosave_render_settings.batch_active = True
		print('Batch Render Process Started')
		
		if context.scene.autosave_render_settings.batch_type == 'imgs':
			# Get source folder and target names
			source_folder = bpy.path.abspath(context.scene.autosave_render_settings.batch_images_location)
			if os.path.isdir(source_folder):
				# Image extensions attribute is undocumented
				# https://blenderartists.org/t/bpy-ops-image-open-supported-formats/1237197/6
				source_images = [f for f in os.listdir(source_folder) if f.lower().endswith(tuple(bpy.path.extensions_image))]
			else:
				context.scene.autosave_render_settings.batch_active = False
				print('VF Autosave Batch Render: Image source directory not found.')
				return {'CANCELLED'}
			
			# Get target
			target_material = context.scene.autosave_render_settings.batch_images_material
			target_node = context.scene.autosave_render_settings.batch_images_node
			target = None
			if bpy.data.materials.get(target_material) and bpy.data.materials[target_material].node_tree.nodes.get(target_node) and bpy.data.materials[target_material].node_tree.nodes.get(target_node).type == 'TEX_IMAGE':
				target = bpy.data.materials[target_material].node_tree.nodes.get(target_node)
			else:
				context.scene.autosave_render_settings.batch_active = False
				print('VF Autosave Batch Render: Target material node not found.')
				return {'CANCELLED'}
			
			# Save current image, if assigned
			original_image = None
			if target.image.has_data:
				original_image = bpy.data.materials[target_material].node_tree.nodes.get(target_node).image
			
			for img_file in source_images:
				# Import as new image if it doesn't already exist
				image = bpy.data.images.load(os.path.join(source_folder, img_file), check_existing=True)
				
				# Set node image to the new image
				target.image = image
				
				# Render
				if context.scene.autosave_render_settings.batch_range == 'still':
					# Render Still
					bpy.ops.render.render(animation=False, write_still=True, use_viewport=True)
				else:
					# Sequence
					bpy.ops.render.render(animation=True, use_viewport=True)
			
			# Reset node to original texture, if previously assigned
			if original_image:
				target.image = original_image
		
		context.scene.autosave_render_settings.batch_active = False
		return {'FINISHED'}

###########################################################################
# View 3D Batch Render UI rendering class
		
class VFTOOLS_PT_autosave_batch_setup(bpy.types.Panel):
	bl_idname = 'VFTOOLS_PT_batch_render_setup'
	bl_label = 'Batch Render'
	bl_description = 'Manage batch rendering options'
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = 'VF Tools'
	bl_order = 16
	bl_options = {'DEFAULT_CLOSED'}
	
	@classmethod
	def poll(cls, context):
		return True
	
	def draw_header(self, context):
		try:
			layout = self.layout
		except Exception as exc:
			print(str(exc) + ' | Error in VF Autosave Render + Output Variables: Batch Render panel header')
			
	def draw(self, context):
#		try:
		if True:
			# UI Layout
			layout = self.layout
#			layout.use_property_split = True
			layout.use_property_decorate = False # No animation
			
			# General variables
			batch_count = 0
			batch_error = ''
			batch_start = 'Batch render '
			
			# Batch type
			layout.prop(context.scene.autosave_render_settings, 'batch_type', text='')
			
			# Settings for Cameras
			
			# Settings for Collections
			
			# Settings for Items
			
			# Settings for Images
			if context.scene.autosave_render_settings.batch_type == 'imgs':
				# Source directory
				layout.prop(context.scene.autosave_render_settings, 'batch_images_location', text='')
				
				# Button to asign material node
				# Only if valid selection is available
				target = layout.row()
				target_text = 'Assign Image Target'
				
				# List the assigned material node if it exists
				box = layout.box()
				# Material and Node feedback (and remove the reference if it no longer exists)
				if not (bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.active_material and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.type == 'TEX_IMAGE'):
#					box.label(text = 'Select object > material > image node to assign target')
					target_text = 'Select object > material > image node to assign target'
				else:
					target_text = 'Assign: ' + bpy.context.view_layer.objects.active.active_material.name + ' > ' + bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.name
				
				if bpy.data.materials.get(context.scene.autosave_render_settings.batch_images_material) and bpy.data.materials[context.scene.autosave_render_settings.batch_images_material].node_tree.nodes.get(context.scene.autosave_render_settings.batch_images_node):
					box.label(text = 'Target: ' + context.scene.autosave_render_settings.batch_images_material + ' > ' + context.scene.autosave_render_settings.batch_images_node)
				elif len(context.scene.autosave_render_settings.batch_images_material) > 0:
					box.label(text = 'Select object > material > image node to assign target')
				
				# Insert target operator into element above the feedback box (this is done out of order to collect necessary data)
				target.operator(VF_autosave_render_batch_assign_image_target.bl_idname, text = target_text)
				
				# Set batch count
				absolute_source_path = bpy.path.abspath(context.scene.autosave_render_settings.batch_images_location)
				if os.path.isdir(absolute_source_path):
					# Image extensions attribute is undocumented
					# https://blenderartists.org/t/bpy-ops-image-open-supported-formats/1237197/6
					image_files = [f for f in os.listdir(absolute_source_path) if f.lower().endswith(tuple(bpy.path.extensions_image))]
					batch_count = len(image_files)
				
				batch_error = 'Missing source directory'
			
			# Batch range setting (still or sequence)
			layout.prop(context.scene.autosave_render_settings, 'batch_range', expand = True)
			
			# Set variables
			batch_start += str(batch_count)
			batch_start += ' still' if context.scene.autosave_render_settings.batch_range == 'still' else ' sequence'
			batch_start += 's' if batch_count > 1 else ''
			
			# Start Batch Render button with title feedback
			button = layout.row()
			if batch_count == 0:
				button.active = False
				button.enabled = False
				button.operator(VF_autosave_render_batch.bl_idname, text=batch_error)
			else:
				button.operator(VF_autosave_render_batch.bl_idname, text=batch_start)
#		except Exception as exc:
#			print(str(exc) + ' | Error in VF Autosave Render + Output Variables: Batch Render panel')



###########################################################################
# Addon registration functions

classes = (AutosaveRenderPreferences, AutosaveRenderSettings, RENDER_PT_autosave_video, RENDER_PT_autosave_render, AutosaveRenderVariablePopup, AutosaveRenderVariableCopy, VF_autosave_render_batch_assign_image_target, VF_autosave_render_batch, VFTOOLS_PT_autosave_batch_setup)

def register():
	for cls in classes:
		bpy.utils.register_class(cls)
	bpy.types.Scene.autosave_render_settings = bpy.props.PointerProperty(type=AutosaveRenderSettings)
	# Using init instead of render_pre means that the entire animation render time is tracked instead of just the final frame
	# bpy.app.handlers.render_pre.append(autosave_render_start)
	bpy.app.handlers.render_init.append(autosave_render_start)
	# Using render_post to calculate estimated time remaining only for animations (when more than one frame is rendered in sequence)
	bpy.app.handlers.render_post.append(autosave_render_estimate)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.append(autosave_render)
	bpy.app.handlers.render_cancel.append(autosave_render)
	bpy.app.handlers.render_complete.append(autosave_render)
	# Render estimate display
	bpy.types.IMAGE_MT_editor_menus.append(image_viewer_feedback_display)
	# Variable info popup
	bpy.types.RENDER_PT_output.prepend(RENDER_PT_output_path_variable_list)
	bpy.types.RENDER_PT_output.append(RENDER_PT_total_render_time_display)
	bpy.types.NODE_PT_active_node_properties.prepend(NODE_PT_output_path_variable_list)
	## Update FFmpeg location
	bpy.context.preferences.addons[__name__].preferences.check_ffmpeg_location()
	bpy.context.preferences.addons[__name__].preferences.check_macos_say_location()

def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
	del bpy.types.Scene.autosave_render_settings
	# Using init instead of render_pre means that the entire animation render time is tracked instead of just the final frame
	# bpy.app.handlers.render_pre.remove(autosave_render_start)
	bpy.app.handlers.render_init.remove(autosave_render_start)
	# Using render_post to calculate estimated time remaining only for animations (when more than one frame is rendered in sequence)
	bpy.app.handlers.render_post.remove(autosave_render_estimate)
	# Using cancel and complete, instead of render_post, prevents saving an image for every frame in an animation
	# bpy.app.handlers.render_post.remove(autosave_render)
	bpy.app.handlers.render_cancel.remove(autosave_render)
	bpy.app.handlers.render_complete.remove(autosave_render)
	# Render estimate display
	bpy.types.IMAGE_MT_editor_menus.remove(image_viewer_feedback_display)
	# Variable info popup
	bpy.types.RENDER_PT_output.remove(RENDER_PT_output_path_variable_list)
	bpy.types.RENDER_PT_output.remove(RENDER_PT_total_render_time_display)
	bpy.types.NODE_PT_active_node_properties.remove(NODE_PT_output_path_variable_list)

if __name__ == "__main__":
	register()