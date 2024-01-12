bl_info = {
	"name": "VF Autosave Render + Output Variables",
	"author": "John Einselen - Vectorform LLC, based on work by tstscr(florianfelix)",
	"version": (2, 8, 3),
	"blender": (3, 2, 0),
	"location": "Scene Output Properties > Output Panel > Autosave Render",
	"description": "Automatically saves rendered images with custom naming",
	"doc_url": "https://github.com/jeinselenVF/VF-BlenderAutosaveRender",
	"tracker_url": "https://github.com/jeinselenVF/VF-BlenderAutosaveRender/issues",
	"category": "Render"}

# General features
import bpy
from bpy.app.handlers import persistent
import datetime
import time
import json
# File paths
import os
from pathlib import Path
# Variable data
import platform
from re import findall, search, sub, M as multiline
# FFmpeg system access
import subprocess
from shutil import which
# Email notifications
import smtplib
from email.mime.text import MIMEText
# Pushover notifications
import requests

# Format validation lists
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

# Available variables
# Includes both headers (string starting with "title,") and variables (string with brackets, commas segment multi-variable lines)
variableArray = ["title,Project,SCENE_DATA",
					"{project}", "{scene}", "{viewlayer}", "{collection}", "{camera}", "{item}", "{material}", "{node}",
				"title,Image,NODE_COMPOSITING",
					"{display}", "{colorspace}", "{look}", "{exposure}", "{gamma}", "{curves}", "{compositing}",
				"title,Render,SCENE",
					"{engine}", "{device}", "{samples}", "{features}", "{duration}", "{rtime}", "{rH},{rM},{rS}",
				"title,System,DESKTOP",
					"{host}", "{processor}", "{platform}", "{system}", "{release}", "{python}", "{blender}",
				"title,Identifier,COPY_ID",
					"{date}", "{y},{m},{d}", "{time}", "{H},{M},{S}", "{serial}", "{frame}", "{batch}"]



###########################################################################
# Pre-render function
# •Set render status variables
# •Save start time for calculations
# •Replace output variables

@persistent
def autosave_render_start(scene):
	# Save start time in seconds as a string to the addon settings
	bpy.context.scene.autosave_render_settings.start_date = str(time.time())
	# Set estimated render time active to false (must render at least one frame before estimating time remaining)
	bpy.context.scene.autosave_render_settings.estimated_render_time_active = False
	# Set video sequence tracking (separate from render active above)
	bpy.context.scene.autosave_render_settings.autosave_video_sequence = False
	bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = False
	
	# Track usage of the output serial usage globally to ensure it can be accessed before/after rendering
	# Set it to false ahead of processing to ensure no errors occur (usually only if there's a crash of some sort)
	bpy.context.scene.autosave_render_settings.output_file_serial_used = False
	
	# Filter output file path if enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.render_output_variables:
		# Save original file path
		bpy.context.scene.autosave_render_settings.output_file_path = filepath = scene.render.filepath
		
		# Check if the serial variable is used
		if '{serial}' in filepath:
			filepath = filepath.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
			bpy.context.scene.autosave_render_settings.output_file_serial_used = True
			
		# Replace scene filepath output with the processed version
		scene.render.filepath = replaceVariables(filepath)
		
	# Filter compositing node file path if turned on in the plugin settings and compositing is enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.render_output_variables and bpy.context.scene.use_nodes:
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
				# Replace dynamic variables
				if '{serial}' in node.base_path:
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				node.base_path = replaceVariables(node.base_path, serial=bpy.context.scene.autosave_render_settings.output_file_serial)
				
				# Save and then process the sub-path property of each file slot
				for i, slot in enumerate(node.file_slots):
					node_settings[node.name]["file_slots"][i] = {
						"path": slot.path
					}
					# Replace dynamic variables
					if '{serial}' in slot.path:
						bpy.context.scene.autosave_render_settings.output_file_serial_used = True
					slot.path = replaceVariables(slot.path, serial=bpy.context.scene.autosave_render_settings.output_file_serial)
					
		# Convert the dictionary to JSON format and save to the plugin preferences for safekeeping while rendering
		bpy.context.scene.autosave_render_settings.output_file_nodes = json.dumps(node_settings)



###########################################################################
# During render function
# •Remaining render time estimation

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
# Post-render function
# •Compile output video using FFmpeg
# •Autosave final rendered image
# •Reset render status variables
# •Reset output paths with original keywords
# •Send render complete alerts
# •Save log file

@persistent
def autosave_render_end(scene):
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
		# Create absolute path and strip trailing spaces
		absolute_path = bpy.path.abspath(scene.render.filepath).rstrip()
		# Replace frame number placeholder with asterisk or add trailing asterisk
		if "#" in absolute_path:
			absolute_path = sub(r'#+(?!.*#)', "*", absolute_path)
		else:
			absolute_path += "*"
		# Create input image glob pattern
		glob_pattern = '-pattern_type glob -i "' + absolute_path + scene.render.file_extension + '"'
		# Create floating point FPS value
		fps_float = '-r ' + str(scene.render.fps / scene.render.fps_base)
		
		# ProRes output
		if bpy.context.scene.autosave_render_settings.autosave_video_prores:
			# Set FFmpeg processing to true so the Image View window can display status
			bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = True
			if len(bpy.context.scene.autosave_render_settings.autosave_video_prores_location) > 1:
				# Replace with custom string
				output_path = bpy.context.scene.autosave_render_settings.autosave_video_prores_location
				# Replace dynamic variables
				if '{serial}' in output_path:
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				output_path = replaceVariables(output_path, rendertime=render_time, serial=bpy.context.scene.autosave_render_settings.output_file_serial)
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
			
			# Print command to the terminal
			print('FFmpeg ProRes command:')
			print(ffmpeg_command)
			print('')
			
			# Run FFmpeg command
			try:
				subprocess.call(ffmpeg_command, shell=True)
				print('')
			except Exception as exc:
				print(str(exc) + " | Error in VF Autosave Render: failed to process FFmpeg ProRes command")
		
		# MP4 output
		if bpy.context.scene.autosave_render_settings.autosave_video_mp4:
			# Set FFmpeg processing to true so the Image View window can display status
			bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = True
			if len(bpy.context.scene.autosave_render_settings.autosave_video_mp4_location) > 1:
				# Replace with custom string
				output_path = bpy.context.scene.autosave_render_settings.autosave_video_mp4_location
				# Replace dynamic variables
				if '{serial}' in output_path:
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				output_path = replaceVariables(output_path, rendertime=render_time, serial=bpy.context.scene.autosave_render_settings.output_file_serial)
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
			
			# Print command to the terminal
			print('FFmpeg MP4 command:')
			print(ffmpeg_command)
			print('')
			
			# Run FFmpeg command
			try:
				subprocess.call(ffmpeg_command, shell=True)
				print('')
			except Exception as exc:
				print(str(exc) + " | Error in VF Autosave Render: failed to process FFmpeg MP4 command")
		
		# Custom output
		if bpy.context.scene.autosave_render_settings.autosave_video_custom:
			# Set FFmpeg processing to true so the Image View window can display status
			bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = True
			if len(bpy.context.scene.autosave_render_settings.autosave_video_custom_location) > 1:
				# Replace with custom string
				output_path = bpy.context.scene.autosave_render_settings.autosave_video_custom_location
				# Replace dynamic variables
				if '{serial}' in output_path:
					bpy.context.scene.autosave_render_settings.output_file_serial_used = True
				output_path = replaceVariables(output_path, rendertime=render_time, serial=bpy.context.scene.autosave_render_settings.output_file_serial)
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
			
			# Print command to the terminal
			print('FFmpeg custom command:')
			print(ffmpeg_command)
			print('')
			
			# Run FFmpeg command
			try:
				subprocess.call(ffmpeg_command, shell=True)
				print('')
			except Exception as exc:
				print(str(exc) + " | Error in VF Autosave Render: failed to process FFmpeg custom command")
	
	# Increment the output serial number if it was used any output path
	if bpy.context.scene.autosave_render_settings.output_file_serial_used:
		bpy.context.scene.autosave_render_settings.output_file_serial += 1
	
	# Set video sequence status to false
	bpy.context.scene.autosave_render_settings.autosave_video_sequence = False
	bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing = False
	
	# Restore unprocessed file path if processing is enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.render_output_variables and bpy.context.scene.autosave_render_settings.output_file_path:
		scene.render.filepath = bpy.context.scene.autosave_render_settings.output_file_path
	
	# Restore unprocessed node output file path if processing is enabled, compositing is enabled, and a file output node exists with the default node name
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.render_output_variables and bpy.context.scene.use_nodes and len(bpy.context.scene.autosave_render_settings.output_file_nodes) > 2:
		
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
	if (bpy.context.preferences.addons['VF_autosaveRender'].preferences.enable_autosave_render) and bpy.data.filepath:
		
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
		# The autosave serial number and override are separate from the project serial number
		serialUsedGlobal = False
		serialUsed = False
		serialNumber = -1
		if '{serial}' in filepath:
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_override:
				serialNumber = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_serial_global
				serialUsedGlobal = True
			else:
				serialNumber = bpy.context.scene.autosave_render_settings.file_serial
				serialUsed = True
		
		# Replace global variables in the output path string
		filepath = replaceVariables(filepath, rendertime=render_time, serial=serialNumber)
		
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
			files = [f for f in os.listdir(filepath) if f.startswith(projectname) and f.lower().endswith(IMAGE_EXTENSIONS)]
			
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
			filename = '{project} {engine} {duration}'
		else:
			# Load custom file name with override
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_override:
				filename = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_name_custom_global
			else:
				filename = bpy.context.scene.autosave_render_settings.file_name_custom
		
		if '{serial}' in filename:
			if bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_location_override:
				serialNumber = bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_serial_global
				serialUsedGlobal = True
			else:
				serialNumber = bpy.context.scene.autosave_render_settings.file_serial
				serialUsed = True
		
		# Replace global variables in the output name string
		filename = replaceVariables(filename, rendertime=render_time, serial=serialNumber)
		
		# Finish local and global serial number updates
		if serialUsedGlobal:
			bpy.context.preferences.addons['VF_autosaveRender'].preferences.file_serial_global += 1
		if serialUsed:
			bpy.context.scene.autosave_render_settings.file_serial += 1
		
		# Combine file path and file name using system separator, add extension
		filepath = os.path.join(filepath, filename) + extension
		
		# Save image file
		image = bpy.data.images['Render Result']
		if not image:
			print('VF Autosave Render: Render Result not found. Image not saved.')
			return {'CANCELLED'}
		
		# Please note that multilayer EXR files are currently unsupported in the Python API - https://developer.blender.org/T71087
		image.save_render(filepath, scene=None) # Consider using bpy.context.scene if different compression settings are desired per-scene
		
		# Restore original user settings for render output
		scene.render.image_settings.file_format = original_format
		scene.render.image_settings.color_mode = original_colormode
		scene.render.image_settings.color_depth = original_colordepth
	
	# Render complete notifications, only if the time spent rendering exceeds the minimum time defined in the preferences
	if render_time > float(bpy.context.preferences.addons['VF_autosaveRender'].preferences.minimum_time):
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_enable:
			# Subject line variable replacement
			subject = replaceVariables(
				bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_subject,
				rendertime=render_time,
				serial=bpy.context.scene.autosave_render_settings.output_file_serial
				)
			# Body text variable replacement
			message = replaceVariables(
				bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_message,
				rendertime=render_time,
				serial=bpy.context.scene.autosave_render_settings.output_file_serial
				)
			send_email(subject, message)
		
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_enable and len(bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_key) == 30 and len(bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_app) == 30:
			subject = replaceVariables(
				bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_subject,
				rendertime=render_time,
				serial=bpy.context.scene.autosave_render_settings.output_file_serial
				)
			message = replaceVariables(
				bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_message,
				rendertime=render_time,
				serial=bpy.context.scene.autosave_render_settings.output_file_serial
				)
			send_pushover(subject, message)
		
		# MacOS Siri text-to-speech announcement
		# Re-check Say location just to be extra-sure (otherwise this is only checked when the add-on is first enable)
		bpy.context.preferences.addons[__name__].preferences.check_macos_say_location()
		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.macos_say_exists and bpy.context.preferences.addons['VF_autosaveRender'].preferences.macos_say_enable:
			message = replaceVariables(
				bpy.context.preferences.addons['VF_autosaveRender'].preferences.macos_say_message,
				rendertime=render_time,
				serial=bpy.context.scene.autosave_render_settings.output_file_serial
				)
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
# Variable replacement function
# •Prepopulate data that requires more logic
# •Replace all variables
# 	•Replaces {duration}{rtime}{rH}{rM}{rS} only if valid 0.0+ float is provided
# 	•Replaces {serial} only if valid 0+ integer is provided

def replaceVariables(string, rendertime=-1.0, serial=-1):
	# Get scene from context
	scene = bpy.context.scene
	
	# Get render engine feature sets
	if bpy.context.engine == 'BLENDER_WORKBENCH':
		renderEngine = 'Workbench'
		renderDevice = 'GPU'
		renderSamples = scene.display.render_aa
		renderFeatures = scene.display.shading.light.title().replace("Matcap", "MatCap") + '+' + scene.display.shading.color_type.title()

	elif bpy.context.engine == 'BLENDER_EEVEE':
		renderEngine = 'Eevee'
		renderDevice = 'GPU'
		renderSamples = str(scene.eevee.taa_render_samples) + '+' + str(scene.eevee.sss_samples) + '+' + str(scene.eevee.volumetric_samples)
		renderFeaturesArray = []
		if scene.eevee.use_gtao:
			renderFeaturesArray.append('AO')
		if scene.eevee.use_bloom:
			renderFeaturesArray.append('Bloom')
		if scene.eevee.use_ssr:
			renderFeaturesArray.append('SSR')
		if scene.eevee.use_motion_blur:
			renderFeaturesArray.append('MB' + str(scene.eevee.motion_blur_steps))
		renderFeatures = 'None' if len(renderFeaturesArray) == 0 else '+'.join(renderFeaturesArray)

	elif bpy.context.engine == 'CYCLES':
		renderEngine = 'Cycles'
		renderDevice = scene.cycles.device
		# Add compute device type if GPU is enabled
		# if renderDevice == "GPU":
			# renderDevice += '_' + bpy.context.preferences.addons["cycles"].preferences.compute_device_type
		renderSamples = str(round(scene.cycles.adaptive_threshold, 4)) + '+' + str(scene.cycles.samples) + '+' + str(scene.cycles.adaptive_min_samples)
		renderFeatures = str(scene.cycles.max_bounces) + '+' + str(scene.cycles.diffuse_bounces) + '+' + str(scene.cycles.glossy_bounces) + '+' + str(scene.cycles.transmission_bounces) + '+' + str(scene.cycles.volume_bounces) + '+' + str(scene.cycles.transparent_max_bounces)

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
		renderSamples = str(scene.rpr.limits.min_samples) + '+' + str(scene.rpr.limits.max_samples) + '+' + str(round(scene.rpr.limits.noise_threshold, 4))
		renderFeatures = str(scene.rpr.max_ray_depth) + '+' + str(scene.rpr.diffuse_depth) + '+' + str(scene.rpr.glossy_depth) + '+' + str(scene.rpr.refraction_depth) + '+' + str(scene.rpr.glossy_refraction_depth) + '+' + str(scene.rpr.shadow_depth)

	elif bpy.context.engine == 'LUXCORE':
		renderEngine = 'LuxCore'
		renderDevice = 'CPU' if scene.luxcore.config.device == 'CPU' else 'GPU'
		# Samples returns the halt conditions for time, samples, and/or noise threshold
		renderSamples = ''
		if scene.luxcore.halt.use_time:
			renderSamples += str(scene.luxcore.halt.time) + 's'
		if scene.luxcore.halt.use_samples:
			if len(renderSamples) > 0:
				renderSamples += '+'
			renderSamples += str(scene.luxcore.halt.samples)
		if scene.luxcore.halt.use_noise_thresh:
			if len(renderSamples) > 0:
				renderSamples += '+'
			renderSamples += str(scene.luxcore.halt.noise_thresh) + '+' + str(scene.luxcore.halt.noise_thresh_warmup) + '+' + str(scene.luxcore.halt.noise_thresh_step)
		# Features include the number of paths or bounces (depending on engine selected) and denoising if enabled
		if scene.luxcore.config.engine == 'PATH':
			renderEngine += '-Path'
			renderFeatures = str(scene.luxcore.config.path.depth_total) + '+' + str(scene.luxcore.config.path.depth_diffuse) + '+' + str(scene.luxcore.config.path.depth_glossy) + '+' + str(scene.luxcore.config.path.depth_specular)
		else:
			renderEngine += '-Bidir'
			renderFeatures = str(scene.luxcore.config.bidir_path_maxdepth) + '+' + str(scene.luxcore.config.bidir_light_maxdepth)
		if scene.luxcore.denoiser.enabled:
			renderFeatures += '+' + str(scene.luxcore.denoiser.type)

	else:
		renderEngine = bpy.context.engine
		renderDevice = 'unknown'
		renderSamples = 'unknown'
		renderFeatures = 'unknown'
	
	# Get conditional project variables Item > Material > Node
	projectItem = projectMaterial = projectNode = 'None'
	if bpy.context.view_layer.objects.active:
		# Set active object name
		projectItem = bpy.context.view_layer.objects.active.name
		if bpy.context.view_layer.objects.active.active_material:
			# Set active material slot name
			projectMaterial = bpy.context.view_layer.objects.active.active_material.name
			if bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active:
				# Set active node name or image name if available
				if bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.type == 'TEX_IMAGE' and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.image.has_data:
					projectNode = bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.image.name
				else:
					projectNode = bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.name
	
	# Set node name to the Batch Render Target if active and available
	if scene.autosave_render_settings.batch_active and scene.autosave_render_settings.batch_type == 'imgs' and bpy.data.materials.get(scene.autosave_render_settings.batch_images_material) and bpy.data.materials[scene.autosave_render_settings.batch_images_material].node_tree.nodes.get(scene.autosave_render_settings.batch_images_node):
		projectNode = bpy.data.materials[scene.autosave_render_settings.batch_images_material].node_tree.nodes.get(scene.autosave_render_settings.batch_images_node).image.name
	
	# Remove file extension from image node names (this could be unhelpful when comparing renders with .psd versus .jpg texture sources)
	projectNode = sub(r'\.\w{3,4}$', '', projectNode)
	
	# Using "replace" instead of "format" because format fails ungracefully when an exact match isn't found
	# Project variables
	string = string.replace("{project}", os.path.splitext(os.path.basename(bpy.data.filepath))[0])
	string = string.replace("{scene}", scene.name)
	string = string.replace("{viewlayer}", bpy.context.view_layer.name)
	string = string.replace("{collection}", scene.autosave_render_settings.batch_collection_name if len(scene.autosave_render_settings.batch_collection_name) > 0 else bpy.context.collection.name) # Alt: bpy.context.view_layer.active_layer_collection.name
	string = string.replace("{camera}", scene.camera.name)
	string = string.replace("{item}", projectItem)
	string = string.replace("{material}", projectMaterial)
	string = string.replace("{node}", projectNode)
	
	# Image variables
	sceneOverride = scene.render.image_settings if bpy.context.scene.render.image_settings.color_management == "OVERRIDE" else scene
	string = string.replace("{display}", sceneOverride.display_settings.display_device.replace(" ", "").replace(".", ""))
	string = string.replace("{viewtransform}", "{colorspace}") # Alternative variable (backwards compatibility may be removed at a later date)
	string = string.replace("{colorspace}", "{space}") # Alternative variable (backwards compatibility may be removed at a later date)
	string = string.replace("{space}", sceneOverride.view_settings.view_transform.replace(" ", ""))
	string = string.replace("{look}", sceneOverride.view_settings.look.replace(" ", "").replace("AgX-", "").replace("FalseColor-", ""))
	string = string.replace("{exposure}", str(sceneOverride.view_settings.exposure))
	string = string.replace("{gamma}", str(sceneOverride.view_settings.gamma))
	string = string.replace("{curves}", "Curves" if sceneOverride.view_settings.use_curve_mapping else "None")
	string = string.replace("{compositing}", "Compositing" if scene.use_nodes else "None")
	
	# Rendering variables
	string = string.replace("{renderengine}", "{engine}") # Alternative variable (backwards compatibility may be removed at a later date)
	string = string.replace("{engine}", renderEngine)
	string = string.replace("{device}", renderDevice)
	string = string.replace("{samples}", renderSamples)
	string = string.replace("{features}", renderFeatures)
	if rendertime >= 0.0: # Only enabled if a value is supplied
		string = string.replace("{rendertime}", "{duration}") # Alternative variable (backwards compatibility may be removed at a later date)
		string = string.replace("{duration}", str(rendertime) + 's')
		rH, rM, rS = secondsToStrings(rendertime)
		string = string.replace("{rtime}", rH + '-' + rM + '-' + rS)
		string = string.replace("{rH}", rH)
		string = string.replace("{rM}", rM)
		string = string.replace("{rS}", rS)
	
	# System variables
	string = string.replace("{host}", platform.node().split('.')[0])
	string = string.replace("{processor}", platform.processor()) # Alternate: platform.machine() provides the same information in many cases
	string = string.replace("{platform}", platform.platform())
	string = string.replace("{system}", platform.system().replace("Darwin", "macOS")) # Alternate: {os}
	string = string.replace("{release}", platform.mac_ver()[0] if platform.system() == "Darwin" else platform.release()) # Alternate: {system}
	string = string.replace("{python}", platform.python_version())
	string = string.replace("{version}", "{blender}") # Alternative variable (backwards compatibility may be removed at a later date)
	string = string.replace("{blender}", bpy.app.version_string + '-' + bpy.app.version_cycle)
	
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
	if serial >= 0: # Only enabled if a value is supplied
		string = string.replace("{serial}", format(serial, '04'))
	string = string.replace("{frame}", format(scene.frame_current, '04'))
	# Consider adding hash-mark support for inserting frames: sub(r'#+(?!.*#)', "", absolute_path)
	# Batch variables
	string = string.replace("{index}", "{batch}") # Alternative variable (backwards compatibility may be removed at a later date)
	string = string.replace("{batch}", format(scene.autosave_render_settings.batch_index, '04'))
	return string



###########################################################################
# Time conversion functions (because datetime doesn't like zero-numbered days or hours over 24)
# •Convert float seconds into string as [hour, minute, second] array (hours expand indefinitely, will not roll over into days)
# •Convert float seconds into string in HH:MM:SS.## format (hours expand indefinitely, will not roll over into days)
# •Convert string in HH:MM:SS.## format into float seconds

def secondsToStrings(sec):
	seconds, decimals = divmod(float(sec), 1)
	minutes, seconds = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)
	return [
		"%d" % (hours),
		"%02d" % (minutes),
		"%02d.%02d" % (seconds, round(decimals*100))
	]

def secondsToReadable(seconds):
	h, m, s = secondsToStrings(seconds)
	return h + ":" + m + ":" + s

def readableToSeconds(readable):
	hours, minutes, seconds = readable.split(':')
	return int(hours)*3600 + int(minutes)*60 + float(seconds)



###########################################################################
# Copy string to clipboard

class AutosaveRenderCopyToClipboard(bpy.types.Operator):
	"""Copy variable to the clipboard"""
	bl_label = "Copy to clipboard"
	bl_idname = "vf.autosave_render_copy_to_clipboard"
	bl_options = {'REGISTER', 'INTERNAL'}
	
	string: bpy.props.StringProperty()
	
	def invoke(self, context, event):
		context.window_manager.clipboard = self.string
		
		# Close the popup panel by temporarily moving the mouse
		x, y = event.mouse_x, event.mouse_y
		context.window.cursor_warp(10, 10)
		move_back = lambda: context.window.cursor_warp(x, y)
		bpy.app.timers.register(move_back, first_interval=0.001)
		
		return {'FINISHED'}



###########################################################################
# Notification system functions
# •Send email notification
# •Send Pushover notification

def send_email(subject, message):
	try:
		msg = MIMEText(message)
		msg['Subject'] = subject
		msg['From'] = bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_from
		msg['To'] = bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_to
		with smtplib.SMTP_SSL(bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_server, bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_port) as smtp_server:
			smtp_server.login(bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_from, bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_password)
			smtp_server.sendmail(bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_from, bpy.context.preferences.addons['VF_autosaveRender'].preferences.email_to.split(', '), msg.as_string())
	except Exception as exc:
		print(str(exc) + " | Error in VF Autosave Render: failed to send email notification")
		
def send_pushover(subject, message):
	try:
		r = requests.post('https://api.pushover.net/1/messages.json', data = {
			"token": bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_app,
			"user": bpy.context.preferences.addons['VF_autosaveRender'].preferences.pushover_key,
			"title": subject,
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



###########################################################################
# Global user preferences and UI rendering class

class AutosaveRenderPreferences(bpy.types.AddonPreferences):
	bl_idname = __name__

	# Global Variables
	render_output_variables: bpy.props.BoolProperty(
		name='Render Variables',
		description='Implements dynamic keywords in the Output directory and Compositing tab "File Output" nodes',
		default=True)
	
	# Autosave Images
	enable_autosave_render: bpy.props.BoolProperty(
		name="Autosave Images",
		description="Automatically saves numbered or dated images in a directory alongside the project file or in a custom location",
		default=True)
	show_autosave_render_overrides: bpy.props.BoolProperty(
		name="Global Overrides",
		description="Show available global overrides, replacing local project settings",
		default=False)
	
	# Override individual project autosave location and file name settings
	file_location_override: bpy.props.BoolProperty(
		name="Override File Location",
		description='Global override for the per-project directory setting',
		default=False)
	file_location_global: bpy.props.StringProperty(
		name="Global File Location",
		description="Leave a single forward slash to auto generate folders alongside project files",
		default="/",
		maxlen=4096,
		subtype="DIR_PATH")
	
	file_name_override: bpy.props.BoolProperty(
		name="Override File Name",
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
		name="Override File Format",
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
	
	# Autosave Videos - FFMPEG output processing
	ffmpeg_processing: bpy.props.BoolProperty(
		name='Autosave Videos',
		description='Enables FFmpeg image sequence compilation options in the Output panel',
		default=True)
	ffmpeg_location: bpy.props.StringProperty(
		name="FFmpeg location",
		description="System location where the the FFmpeg command line interface is installed",
		default="/opt/local/bin/ffmpeg",
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
	
	# Render Time Tracking
	show_estimated_render_time: bpy.props.BoolProperty(
		name="Show Estimated Render Time",
		description='Adds estimated remaining render time display to the image editor menu bar while rendering',
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
	
	# Render Complete Notifications
	minimum_time: bpy.props.IntProperty(
		name="Minimum Render Time",
		description="Minimum rendering time required before notifications will be enabled, in seconds",
		default=300)
	
	# Email notifications
	email_enable: bpy.props.BoolProperty(
		name='Email Notification',
		description='Enable email notifications',
		default=False)
	email_server: bpy.props.StringProperty(
		name="SMTP Server",
		description="SMTP server address",
		default="smtp.gmail.com",
		maxlen=64)
	email_port: bpy.props.IntProperty(
		name="SMTP Port",
		description="Port number used by the SMTP server",
		default=465)
	email_from: bpy.props.StringProperty(
		name="Username",
		description="Email address of the account emails will be sent from",
		default="user@gmail.com",
		maxlen=64)
	email_password: bpy.props.StringProperty(
		name="Password",
		description="Password of the account emails will be sent from (Gmail accounts require 2FA and a custom single-use App Password)",
		default="password",
		subtype="PASSWORD")
	email_to: bpy.props.StringProperty(
		name="Recipients",
		description="Comma separated list of recipient addresses, use https://freecarrierlookup.com/ to get the correct address for text messages",
		default="email@server.com, 1234567890@carrier.net",
		maxlen=1024)
	email_subject: bpy.props.StringProperty(
		name="Email Subject",
		description="Text string sent as the email subject line",
		default="{project} rendering completed",
		maxlen=1024)
	email_message: bpy.props.StringProperty(
		name="Email Body",
		description="Text string sent as the email body copy",
		default="{project} rendering completed in {rH}:{rM}:{rS} on {host}",
		maxlen=4096)
	
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
	pushover_subject: bpy.props.StringProperty(
		name="Pushover Title",
		description="Notification title that will be sent to Pushover devices",
		default="{project} rendering completed",
		maxlen=1024)
	pushover_message: bpy.props.StringProperty(
		name="Pushover Message",
		description="Notification message that will be sent to Pushover devices",
		default="{project} rendering completed in {rH}:{rM}:{rS} on {host}",
		maxlen=4096)
	
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
		default="{project} rendering completed in {rH} hours, {rM} minutes, and {rS} seconds",
		maxlen=2048)
	
	# Validate the MacOS Say location on plugin registration
	def check_macos_say_location(self):
		# Test if it's a valid path
		self.macos_say_exists = False if which('say') is None else True
	
	
	
	# User Interface
	def draw(self, context):
		layout = self.layout
	
	# General Preferences:
		grid1 = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
		
		# Output variables
		grid1.prop(self, "render_output_variables")
		ops = grid1.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
		ops.postrender = True
		
		# Autosave Videos - FFmpeg Sequencing
		grid1.prop(self, "ffmpeg_processing")
		input = grid1.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
		if not self.ffmpeg_processing:
			input.active = False
			input.enabled = False
		input.prop(self, "ffmpeg_location", text="")
		# Location exists success/fail
		if self.ffmpeg_exists:
			input.label(text="✔︎ installed")
		else:
			input.label(text="✘ missing")
		
		# Autosave Images
		grid1.prop(self, "enable_autosave_render")
		input = grid1.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
		if self.file_location_override or self.file_name_override or self.file_format_override or not self.enable_autosave_render:
			input.separator()
		elif self.show_autosave_render_overrides:
			input.prop(self, "show_autosave_render_overrides", icon = "DISCLOSURE_TRI_DOWN", emboss = False)
		else:
			input.prop(self, "show_autosave_render_overrides", icon = "DISCLOSURE_TRI_RIGHT", emboss = False)
		input.separator()
		
		# Autosave Images - Global Overrides Section
		if (self.show_autosave_render_overrides or self.file_location_override or self.file_name_override or self.file_format_override) and self.enable_autosave_render:
			# Subgrid Layout
			margin = layout.row()
			margin.separator(factor=2.0)
			subgrid = margin.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
			margin.separator(factor=2.0)
			
			# File location
			subgrid.prop(self, "file_location_override")
			input = subgrid.column(align=True)
			if not self.file_location_override:
				input.active = False
				input.enabled = False
			input.prop(self, "file_location_global", text='')
			# Display global serial number if used
			if self.file_location_override and '{serial}' in self.file_location_global:
				input.prop(self, "file_serial_global")
				input.separator()
			
			# File name
			subgrid.prop(self, "file_name_override")
			input = subgrid.column(align=True)
			if not self.file_name_override:
				input.active = False
				input.enabled = False
			input.prop(self, "file_name_type_global", text='', icon='FILE_TEXT')
			if (self.file_name_type_global == 'CUSTOM'):
				input.prop(self, "file_name_custom_global", text='')
				if self.file_name_override and self.file_name_type_global == 'CUSTOM' and '{serial}' in self.file_name_custom_global:
					input.prop(self, "file_serial_global")
				input.separator()
			
			# File format
			subgrid.prop(self, "file_format_override")
			input = subgrid.column()
			if not self.file_format_override:
				input.active = False
				input.enabled = False
			input.prop(self, "file_format_global", text='', icon='FILE_IMAGE')
			if self.file_format_override and self.file_format_global == 'SCENE' and bpy.context.scene.render.image_settings.file_format == 'OPEN_EXR_MULTILAYER':
				error = input.box()
				error.label(text="Python API can only save single layer EXR files")
				error.label(text="Report: https://developer.blender.org/T71087")
		
	# Render Time Data
		layout.separator(factor = 2.0)
		grid2 = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
		
		# Render time preferences
		grid2.prop(self, "show_estimated_render_time")
		grid2.separator()
		
		grid2.prop(self, "show_total_render_time")
		input = grid2.column()
		if not self.show_total_render_time:
			input.active = False
			input.enabled = False
		input.prop(context.scene.autosave_render_settings, 'total_render_time')
		
		grid2.prop(self, "external_render_time")
		input = grid2.column()
		if not self.external_render_time:
			input.active = False
			input.enabled = False
		input.prop(self, "external_log_name", text='')
		
	# Render Completed Notifications
		layout.separator(factor = 2.0)
		grid3 = layout.grid_flow(row_major=True, columns=1, even_columns=True, even_rows=False, align=False)
		
		# Minimum render time before notifications are enabled
		row1 = grid3.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
		row1.label(text="Render Completed Notifications")
		row1.prop(self, "minimum_time", icon="TIME")
		
		# Email notifications
		grid3.prop(self, "email_enable")
		if self.email_enable:
			# Subgrid Layout
			margin = grid3.row()
			margin.separator(factor=2.0)
			subgrid = margin.column()
			margin.separator(factor=2.0)
			
			# Security Warning
			box = subgrid.box()
			warning = box.column(align=True)
			warning.label(text="WARNING:")
			warning.label(text="Blender does not encrypt settings and stores credentials as plain text,")
			warning.label(text="account details entered here are NOT SECURED in the file system")
			
			# Account
			settings1 = subgrid.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=False)
			column1 = settings1.column(align=True)
			column1.label(text="Server")
			column1.prop(self, "email_server", text="", icon="EXPORT")
			column1.prop(self, "email_port")
			column2 = settings1.column(align=True)
			column2.label(text="Account")
			column2.prop(self, "email_from", text="", icon="USER")
			column2.prop(self, "email_password", text="", icon="LOCKED")
			
			# Message
			subgrid.separator(factor=0.5)
			settings2 = subgrid.column(align=True)
			settings2.label(text="Message")
			settings2.prop(self, "email_to", text="", icon="USER")
			settings2.prop(self, "email_subject", text="", icon="FILE_TEXT")
			settings2.prop(self, "email_message", text="", icon="ALIGN_JUSTIFY")
			
			# Spacing
			subgrid.separator(factor=2.0)
		
		# Pushover notifications
		grid3.prop(self, "pushover_enable")
		if self.pushover_enable:
			# Subgrid Layout
			margin = grid3.row()
			margin.separator(factor=2.0)
			subgrid = margin.column()
			margin.separator(factor=2.0)
			
			# Security Warning
			box = subgrid.box()
			warning = box.column(align=True)
			warning.label(text="WARNING:")
			warning.label(text="Blender does not encrypt settings and stores credentials as plain text,")
			warning.label(text="API keys entered here are NOT SECURED in the file system")
			
			# Account
			settings1 = subgrid.column(align=True)
			settings1.label(text="Account")
			row = settings1.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=True)
			row.prop(self, "pushover_key", text="", icon="USER")
			row.prop(self, "pushover_app", text="", icon="MODIFIER_DATA")
			
			if self.pushover_enable and (len(self.pushover_key) != 30 or len(self.pushover_app) != 30):
				warning = settings1.box()
				warning.label(text='Please enter 30-character API strings for both user key and app token', icon="ERROR")
			
			# Message
			subgrid.separator(factor=0.5)
			settings2 = subgrid.column(align=True)
			settings2.label(text="Message")
			settings2.prop(self, "pushover_subject", text="", icon="FILE_TEXT")
			settings2.prop(self, "pushover_message", text="", icon="ALIGN_JUSTIFY")
			
			# Spacing
			subgrid.separator(factor = 2.0)
		
		# Apple MacOS Siri text-to-speech announcement
		if self.macos_say_exists:
			grid3.prop(self, "macos_say_enable")
			if self.macos_say_enable:
				# Subgrid Layout
				margin = grid3.row()
				margin.separator(factor=2.0)
				subgrid = margin.column()
				margin.separator(factor=2.0)
				
				# Message
				subgrid.prop(self, "macos_say_message", text='', icon="PLAY_SOUND")



###########################################################################
# Local project settings

class AutosaveRenderSettings(bpy.types.PropertyGroup):
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
		default="{project}-{serial}-{engine}-{duration}",
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
		default='itms')
	batch_range: bpy.props.EnumProperty(
		name='Range',
		description='Batch render single frame or full timeline sequence',
		items=[
			('img', 'Image', 'Batch render a single frame for each element'),
			('anim', 'Animation', 'Batch render the timeline range for each element')
			],
		default='img')
	
	# Batch cameras
	# Uses the active camera for output variables
	
	# Batch collections
	batch_collection_name: bpy.props.StringProperty(
		name="Collection Name",
		description="Name of the collection currently being rendered (bypasses view_layer settings that aren't updated during processing)",
		default="")
	
	# Batch items
	# Uses the active item for output variables
	
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
	
	# Batch index
	batch_index: bpy.props.IntProperty(
		name="Batch Index (set during rendering)",
		description="Dynamically populated during batch rendering with the current camera, collection, item, or image index integer starting with 0",
		default=0,
		step=1)



###########################################################################
# Output Properties panel UI rendering classes
# •Autosave Videos panel
# •Autosave Render panel

class RENDER_PT_autosave_video(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Autosave Videos"
	bl_parent_id = "RENDER_PT_output"

	@classmethod
	def poll(cls, context):
		return (
			# Check if FFmpeg processing is enabled
			bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_processing
			# Check if the FFmpeg appears to be valid
			and bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_exists
		)
	
	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		
		# Check if the output format is supported by FFmpeg
		if not bpy.context.scene.render.image_settings.file_format in FFMPEG_FORMATS:
			error = layout.box()
			error.label(text='"' + bpy.context.scene.render.image_settings.file_format + '" output format is not supported by FFmpeg')
			error.label(text="Supported image formats: " + ', '.join(FFMPEG_FORMATS))
			layout = layout.column()
			layout.active = False
			layout.enabled = False
		
		# Variable list popup button
		ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
		ops.postrender = True
		
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
	bl_label = "Autosave Images"
	bl_parent_id = "RENDER_PT_output"
	
	@classmethod
	def poll(cls, context):
		return (
			# Check if autosaving images is enabled
			bpy.context.preferences.addons['VF_autosaveRender'].preferences.enable_autosave_render
		)
	
	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
		layout.use_property_split = True
		
		# Variable list popup button
		ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF")
		ops.postrender = True
		
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
# •Variable list popup panel
# •Add variable list button and serial input at the top of the Render tab > Output panel
# •Add variable list button and serial input at the top of the Compositing workspace > Node tab > Properties panel

# Popup panel UI
class AutosaveRenderVariablePopup(bpy.types.Operator):
	"""List of the available variables"""
	bl_label = "Variable List"
	bl_idname = "vf.autosave_render_variable_popup"
	bl_options = {'REGISTER', 'INTERNAL'}
	
	postrender: bpy.props.BoolProperty()
	
	@classmethod
	def poll(cls, context):
		return True
	
	def execute(self, context):
		self.report({'INFO'}, "YES")
		return {'FINISHED'}
	
	def invoke(self, context, event):
		return context.window_manager.invoke_popup(self, width=520)
	
	def draw(self, context):
		layout = self.layout
		grid = self.layout.grid_flow(row_major=True, columns = 5, even_columns = True, even_rows = True)
		for item in variableArray:
			# Display headers
			if item.startswith('title,'):
				x = item.split(',')
				col = grid.column()
				col.label(text = x[1], icon = x[2])
			# Display list elements
			elif item not in ["{duration}", "{rtime}", "{rH},{rM},{rS}", "{frame}"] or self.postrender:
				if ',' in item:
					subrow = col.row(align = True)
					for subitem in item.split(','):
						ops = subrow.operator(AutosaveRenderCopyToClipboard.bl_idname, text = subitem, emboss = False)
						ops.string = subitem
				else:
					ops = col.operator(AutosaveRenderCopyToClipboard.bl_idname, text = item, emboss = False)
					ops.string = item
		layout.label(text = 'Click a variable to copy it to the clipboard', icon = "COPYDOWN")

# Render output UI
def RENDER_PT_output_path_variable_list(self, context):
	if not (False) and bpy.context.preferences.addons['VF_autosaveRender'].preferences.render_output_variables:
		# UI layout for Scene Output
		layout = self.layout
		ops = layout.operator(AutosaveRenderVariablePopup.bl_idname, text = "Variable List", icon = "LINENUMBERS_OFF") # LINENUMBERS_OFF, THREE_DOTS, SHORTDISPLAY, ALIGN_JUSTIFY
		ops.postrender = False
		layout.use_property_decorate = False
		layout.use_property_split = True
		input = layout.row()
		if not '{serial}' in bpy.context.scene.render.filepath:
			input.active = False
			input.enabled = False
		input.prop(context.scene.autosave_render_settings, 'output_file_serial')

# Node output UI
def NODE_PT_output_path_variable_list(self, context):
	if not (False) and bpy.context.preferences.addons['VF_autosaveRender'].preferences.render_output_variables:
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
			ops.postrender = False
			input = layout.row()
			if not '{serial}' in paths:
				input.active = False
				input.enabled = False
			input.prop(context.scene.autosave_render_settings, 'output_file_serial')
			layout.use_property_split = False # Base path interface doesn't specify false, it assumes it, so the UI gets screwed up if we don't reset here



###########################################################################
# Display total render time at the bottom of the Render tab > Output panel

def RENDER_PT_total_render_time_display(self, context):
	if not (False) and bpy.context.preferences.addons['VF_autosaveRender'].preferences.show_total_render_time:
		layout = self.layout
		box = layout.box()
		box.label(text="Total time spent rendering: "+secondsToReadable(bpy.context.scene.autosave_render_settings.total_render_time))



###########################################################################
# Display estimated time remaining in the Image viewer during rendering

def image_viewer_feedback_display(self, context):
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.show_estimated_render_time and bpy.context.scene.autosave_render_settings.estimated_render_time_active:
		self.layout.separator()
		box = self.layout.box()
		box.label(text="  Estimated Time Remaining: " + bpy.context.scene.autosave_render_settings.estimated_render_time_value + " ")
	if bpy.context.scene.autosave_render_settings.autosave_video_sequence_processing:
		self.layout.separator()
		box = self.layout.box()
		box.label(text="  FFmpeg Image Sequence Processing... ")



###########################################################################
# Batch Render Functions
# •Process batch rendering queue
#	•Cameras
#	•Collections
#	•Items (objects and/or lights)
#	•Images (requires specific folder input and target material node)
# •Set target material > node for Batch Render Images

# Process batch rendering queue
class VF_autosave_render_batch(bpy.types.Operator):
	bl_idname = 'render.vf_autosave_render_batch'
	bl_label = 'Begin Batch Render'
	bl_description = "Batch render specified elements"
	bl_space_type = "VIEW_3D"
	
	@classmethod
	def poll(cls, context):
		return ( True )
	
	def invoke(self, context, event):
			return context.window_manager.invoke_props_dialog(self)
	
	def draw(self, context):
		try:
			layout = self.layout
			layout.label(text="Blender will be unresponsive while processing, proceed?")
		except Exception as exc:
			print(str(exc) + ' | Error in VF Autosave Render + Output Variables: Begin Batch Render confirmation header')
	
	def execute(self, context):
		context.scene.autosave_render_settings.batch_active = True
		
		# Preserve manually entered batch index
		original_batch_index = context.scene.autosave_render_settings.batch_index
		
		# Batch render cameras
		if context.scene.autosave_render_settings.batch_type == 'cams':
			# Preserve original active camera
			original_camera = bpy.context.scene.camera
			
			# If cameras are selected
			if len(context.selected_objects) > 0 and len([obj for obj in context.selected_objects if obj.type == 'CAMERA']) > 0:
				source_cameras = [obj for obj in context.selected_objects if obj.type == 'CAMERA']
				
			# If no cameras are selected, check for an active collection with cameras
			elif context.view_layer.active_layer_collection and len(context.view_layer.active_layer_collection.collection.all_objects) > 0 and len([obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type == 'CAMERA']) > 0:
				source_cameras = [obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type == 'CAMERA']
				
			# If still no cameras are available, return cancelled
			else:
				context.scene.autosave_render_settings.batch_active = False
				print('VF Autosave Batch Render: Cameras not found.')
				return {'CANCELLED'}
			
			# Reset batch index value
			context.scene.autosave_render_settings.batch_index = 0
			
			# Render each camera in the list
			for cam in source_cameras:
				# Set rendering camera to current camera
				bpy.context.scene.camera = cam
				
				# Render
				if context.scene.autosave_render_settings.batch_range == 'img':
					# Render Still
					bpy.ops.render.render(animation=False, write_still=True, use_viewport=True)
				else:
					# Sequence
					bpy.ops.render.render(animation=True, use_viewport=True)
				
				# Increment index value
				context.scene.autosave_render_settings.batch_index += 1
				
			# Restore original active camera
			bpy.context.scene.camera = original_camera
		
		# Batch render collections
		if context.scene.autosave_render_settings.batch_type == 'cols':
			# If we need to support direct selection of multiple collections...
			# https://blender.stackexchange.com/questions/249139/selecting-a-collection-via-python
			# ...but for now I'm keeping this simpler
			
			# If child collections exist
			if len(context.view_layer.active_layer_collection.children) > 0:
				source_collections = [col for col in context.view_layer.active_layer_collection.children]
			
			# If no collections are available, return cancelled
			else:
				context.scene.autosave_render_settings.batch_active = False
				print('VF Autosave Batch Render: Collections not found.')
				return {'CANCELLED'}
			
			# Store the render status of each collection and disable
			source_collections_hidden = []
			source_collections_excluded = []
			for col in source_collections:
				# Using both exclude and hide_render status to ensure each collection is for-sure enabled when rendering
				source_collections_hidden.append(col.collection.hide_render)
				source_collections_excluded.append(col.exclude)
				col.collection.hide_render = True
				col.exclude = True
				
			print('hidden status:')
			print(dir(source_collections_hidden))
			print('excluded status:')
			print(dir(source_collections_excluded))
			
			# Reset batch index value
			context.scene.autosave_render_settings.batch_index = 0
			
			# Render each collection in the list
			for col in source_collections:
				# Set current collection name
				context.scene.autosave_render_settings.batch_collection_name = col.name
				
				# Set current collection rendering status
				col.collection.hide_render = False
				col.exclude = False
				
				# Render
				if context.scene.autosave_render_settings.batch_range == 'img':
					# Render Still
					bpy.ops.render.render(animation=False, write_still=True, use_viewport=True)
				else:
					# Sequence
					bpy.ops.render.render(animation=True, use_viewport=True)
					
				# Disable the collection again
				col.collection.hide_render = True
				col.exclude = True
				
				# Increment index value
				context.scene.autosave_render_settings.batch_index += 1
				
			# Restore enabled status
			if len(source_collections_hidden) > 0 and len(source_collections_hidden) == len(source_collections_excluded):
				for i, col in enumerate(source_collections):
					col.collection.hide_render = source_collections_hidden[i]
					col.exclude = source_collections_excluded[i]
			
			# Reset batch rendering variable
			context.scene.autosave_render_settings.batch_collection_name = ''
		
		# Batch render items
		if context.scene.autosave_render_settings.batch_type == 'itms':
			# Preserve original item selection
			original_selection = [obj for obj in context.selected_objects]
			
			# Preserve active item
			original_active = context.view_layer.objects.active
			
			# If non-camera items are selected
			if len(context.selected_objects) > 0 and len([obj for obj in context.selected_objects if obj.type != 'CAMERA']) > 0:
				source_items = [obj for obj in context.selected_objects if obj.type != 'CAMERA']
				
			# If no items are selected, check for an active collection with non-camera items
			elif context.view_layer.active_layer_collection and len(context.view_layer.active_layer_collection.collection.all_objects) > 0 and len([obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type != 'CAMERA']) > 0:
				source_items = [obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type != 'CAMERA']
				
			# If still no items are available, return cancelled
			else:
				context.scene.autosave_render_settings.batch_active = False
				print('VF Autosave Batch Render: Items not found.')
				return {'CANCELLED'}
			
			# Store the render status of each object and disable rendering
			source_items_hidden = []
			for obj in source_items:
				source_items_hidden.append(obj.hide_render)
				obj.hide_render = True
				obj.select_set(False)
			
			# Reset batch index value
			context.scene.autosave_render_settings.batch_index = 0
			
			# Render each item in the list
			for obj in source_items:
				# Set current object to selected, active, and renderable
				obj.select_set(True)
				context.view_layer.objects.active = obj
				obj.hide_render = False
				
				# Render
				if context.scene.autosave_render_settings.batch_range == 'img':
					# Render Still
					bpy.ops.render.render(animation=False, write_still=True, use_viewport=True)
				else:
					# Sequence
					bpy.ops.render.render(animation=True, use_viewport=True)
				
				# Disable the object again (don't worry about active, next loop will reset it)
				obj.select_set(False)
				obj.hide_render = True
				
				# Increment index value
				context.scene.autosave_render_settings.batch_index += 1
			
			# Restore render status
			if len(source_items_hidden) > 0:
				for i, obj in enumerate(source_items):
					obj.hide_render = source_items_hidden[i]
			
			# Restore original selection
			if original_selection:
				for obj in original_selection:
					obj.select_set(True)
			
			# Restore original active item
			if original_active:
				context.view_layer.objects.active = original_active
		
		# Batch render images
		if context.scene.autosave_render_settings.batch_type == 'imgs':
			# Get source folder and target names
			source_folder = bpy.path.abspath(context.scene.autosave_render_settings.batch_images_location)
			source_images = []
			if os.path.isdir(source_folder):
				# Image extensions attribute is undocumented
				# https://blenderartists.org/t/bpy-ops-image-open-supported-formats/1237197/6
				source_images = [f for f in os.listdir(source_folder) if f.lower().endswith(tuple(bpy.path.extensions_image))]
				source_images.sort()
			else:
				context.scene.autosave_render_settings.batch_active = False
				print('VF Autosave Batch Render: Image source directory not found.')
				return {'CANCELLED'}
				# The folder should be checked in the UI before starting, but this is a backup safety if triggered via Python
			
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
			
			# Reset batch index value
			context.scene.autosave_render_settings.batch_index = 0
			
			# Batch render images (assumes we've already cancelled if there's an error with the folder)
			for img_file in source_images:
				# Import as new image if it doesn't already exist
				image = bpy.data.images.load(os.path.join(source_folder, img_file), check_existing=True)
				
				# Set node image to the new image
				target.image = image
				
				# Render
				if context.scene.autosave_render_settings.batch_range == 'img':
					# Render Still
					bpy.ops.render.render(animation=False, write_still=True, use_viewport=True)
				else:
					# Sequence
					bpy.ops.render.render(animation=True, use_viewport=True)
				
				# Increment index value
				context.scene.autosave_render_settings.batch_index += 1
			
			# Reset node to original texture, if previously assigned
			if original_image:
				target.image = original_image
		
		# Restore manually entered batch index
		context.scene.autosave_render_settings.batch_index = original_batch_index
		
		context.scene.autosave_render_settings.batch_active = False
		return {'FINISHED'}

# Set target material > node for Batch Render Images
class VF_autosave_render_batch_assign_image_target(bpy.types.Operator):
	bl_idname = 'render.vf_autosave_render_batch_assign_image_target'
	bl_label = 'Assign image target'
	bl_description = "Assign active node in material as target for batch rendering images"
	bl_space_type = "NODE_EDITOR"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context):
		# Check if necessary object > material > node > node type is selected
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
# Batch Render UI
# •VF Tools > Batch Render Panel
#	•Cameras
#	•Collections
#	•Items (objects and/or lights)
#	•Images (with folder and material node selection)

class VFTOOLS_PT_autosave_batch_setup(bpy.types.Panel):
	bl_idname = 'VFTOOLS_PT_batch_render_setup'
	bl_label = 'Batch Render'
	bl_description = 'Manage batch rendering options'
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = 'VF Tools'
	bl_order = 24
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
		if True:
			# UI Layout
			layout = self.layout
			layout.use_property_decorate = False # No animation
			
			# General variables
			batch_count = 0
			batch_error = False
			
			# Batch type
			input0 = layout.column(align=True)
			input0.prop(context.scene.autosave_render_settings, 'batch_type', text='')
			
			input1 = layout.column(align=True)
			input2 = layout.column(align=True)
			
			# Settings for Cameras
			if context.scene.autosave_render_settings.batch_type == 'cams':
				# Direct selection of cameras
				batch_count = len([obj for obj in context.selected_objects if obj.type == 'CAMERA'])
				
				# Set up feedback message for selected cameras
				if batch_count > 0:
					if batch_count == 1:
						feedback_text=str(batch_count) + ' camera selected'
					else:
						feedback_text=str(batch_count) + ' cameras selected'
					feedback_icon='CAMERA_DATA' # Alt: VIEW_CAMERA
				
				# If no cameras are selected, check for an active collection
				elif context.view_layer.active_layer_collection and len(context.view_layer.active_layer_collection.collection.all_objects) > 0 and len([obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type == 'CAMERA']) > 0:
					batch_count = len([obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type == 'CAMERA'])
					if batch_count == 1:
						feedback_text=str(batch_count) + ' camera in collection'
					else:
						feedback_text=str(batch_count) + ' cameras in collection'
					feedback_icon='OUTLINER_COLLECTION'
				
				# If still no items are selected, display an error
				else:
					feedback_text='Invalid selection'
					feedback_icon='ERROR'
					
				# Display feedback
				feedback = input0.box()
				feedback.label(text=feedback_text, icon=feedback_icon)
			
			# Settings for Collections
			if context.scene.autosave_render_settings.batch_type == 'cols':
				# Collection children (no direct selection of collections currently supported)
				batch_count = len(context.view_layer.active_layer_collection.children)
				
				# Set up feedback message for child collections
				if batch_count > 0:
					if batch_count == 1:
						feedback_text=str(batch_count) + ' sub-collection available'
					else:
						feedback_text=str(batch_count) + ' sub-collections available'
					feedback_icon='OUTLINER_COLLECTION'
					
				# If no collections are available, display an error
				else:
					feedback_text='Invalid selection'
					feedback_icon='ERROR'
					
				# Display feedback
				feedback = input0.box()
				feedback.label(text=feedback_text, icon=feedback_icon)
			
			# Settings for Items
			if context.scene.autosave_render_settings.batch_type == 'itms':
				# Direct selection of items
				batch_count = len([obj for obj in context.selected_objects if obj.type != 'CAMERA'])
				
				# Set up feedback message for selected items
				if batch_count > 0:
					if batch_count == 1:
						feedback_text=str(batch_count) + ' item selected'
					else:
						feedback_text=str(batch_count) + ' items selected'
					feedback_icon='OBJECT_DATA'
				
				# If no items are selected, check for an active collection
				elif context.view_layer.active_layer_collection and len(context.view_layer.active_layer_collection.collection.all_objects) > 0 and len([obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type != 'CAMERA']) > 0:
					batch_count = len([obj for obj in context.view_layer.active_layer_collection.collection.all_objects if obj.type != 'CAMERA'])
					if batch_count == 1:
						feedback_text=str(batch_count) + ' item in collection'
					else:
						feedback_text=str(batch_count) + ' items in collection'
					feedback_icon='OUTLINER_COLLECTION'
				
				# If still no items are selected, display an error
				else:
					feedback_text='Invalid selection'
					feedback_icon='ERROR'
				
				# Display feedback
				feedback = input0.box()
				feedback.label(text=feedback_text, icon=feedback_icon)
			
			# Settings for Images
			if context.scene.autosave_render_settings.batch_type == 'imgs':
				# Source directory
				input1.prop(context.scene.autosave_render_settings, 'batch_images_location', text='')
				
				# Get source folder and image count
				source_folder = bpy.path.abspath(context.scene.autosave_render_settings.batch_images_location)
				if os.path.isdir(source_folder):
					# Image extensions attribute is undocumented
					# https://blenderartists.org/t/bpy-ops-image-open-supported-formats/1237197/6
					source_images = [f for f in os.listdir(source_folder) if f.lower().endswith(tuple(bpy.path.extensions_image))]
					batch_count = len(source_images)
					feedback_text=str(batch_count) + ' images found'
					feedback_icon='IMAGE_DATA'
				else:
					feedback_text='Invalid location'
					feedback_icon='ERROR'
					batch_error = True
				feedback = input1.box()
				feedback.label(text=feedback_text, icon=feedback_icon)
				
				# Material node assignment
				if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.active_material and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active and bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.type == 'TEX_IMAGE':
					target_text = 'Assign ' + bpy.context.view_layer.objects.active.active_material.name + ' > ' + bpy.context.view_layer.objects.active.active_material.node_tree.nodes.active.name
					target_icon = 'IMPORT'
				else:
					target_text = 'Assign Image Node'
					target_icon = 'ERROR'
				input2.operator(VF_autosave_render_batch_assign_image_target.bl_idname, text=target_text)
				
				# List the assigned material node if it exists
				if bpy.data.materials.get(context.scene.autosave_render_settings.batch_images_material) and bpy.data.materials[context.scene.autosave_render_settings.batch_images_material].node_tree.nodes.get(context.scene.autosave_render_settings.batch_images_node):
					feedback_text = context.scene.autosave_render_settings.batch_images_material + ' > ' + context.scene.autosave_render_settings.batch_images_node
					feedback_icon = 'NODE'
				else:
					feedback_text = 'Select object > material > image node'
					feedback_icon = 'ERROR'
					batch_error = True
				feedback = input2.box()
				feedback.label(text=feedback_text, icon=feedback_icon)
			
			# Final settings and start render
			input3 = layout.column(align=True)
			
			# Read-only batch index field
			field = input3.row(align=True)
			field.prop(context.scene.autosave_render_settings, 'batch_index', icon='MODIFIER') # PREFERENCES MODIFIER
			
			# Batch range setting (still or sequence)
			buttons = input3.row(align=True)
			buttons.prop(context.scene.autosave_render_settings, 'batch_range', expand = True)
			
			# Start Batch Render button with title feedback
			button = input3.row(align=True)
			if batch_count == 0 or batch_error:
				button.active = False
				button.enabled = False
				batch_text = 'Batch Render'
				batch_icon = 'ERROR'
			else:
				batch_text = 'Batch Render '
				batch_text += str(batch_count)
				if context.scene.autosave_render_settings.batch_range == 'img':
					batch_text += ' Image'
					batch_icon = 'RENDER_STILL'
				else:
					batch_text += ' Animation'
					batch_icon = 'RENDER_ANIMATION'
				batch_text += 's' if batch_count > 1 else ''
			button.operator(VF_autosave_render_batch.bl_idname, text=batch_text, icon=batch_icon)



###########################################################################
# Addon registration functions
# •Define classes being registered
# •Registration function
# •Unregistration function

classes = (AutosaveRenderPreferences, AutosaveRenderSettings, RENDER_PT_autosave_video, RENDER_PT_autosave_render, AutosaveRenderVariablePopup, AutosaveRenderCopyToClipboard, VF_autosave_render_batch_assign_image_target, VF_autosave_render_batch, VFTOOLS_PT_autosave_batch_setup)

def register():
	for cls in classes:
		bpy.utils.register_class(cls)
	# Settings reference
	bpy.types.Scene.autosave_render_settings = bpy.props.PointerProperty(type=AutosaveRenderSettings)
	# Rendering events
	bpy.app.handlers.render_init.append(autosave_render_start)
	bpy.app.handlers.render_post.append(autosave_render_estimate)
	bpy.app.handlers.render_cancel.append(autosave_render_end)
	bpy.app.handlers.render_complete.append(autosave_render_end)
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
	# Settings reference
	del bpy.types.Scene.autosave_render_settings
	# Rendering events
	bpy.app.handlers.render_init.remove(autosave_render_start)
	bpy.app.handlers.render_post.remove(autosave_render_estimate)
	bpy.app.handlers.render_cancel.remove(autosave_render_end)
	bpy.app.handlers.render_complete.remove(autosave_render_end)
	# Render estimate display
	bpy.types.IMAGE_MT_editor_menus.remove(image_viewer_feedback_display)
	# Variable info popup
	bpy.types.RENDER_PT_output.remove(RENDER_PT_output_path_variable_list)
	bpy.types.RENDER_PT_output.remove(RENDER_PT_total_render_time_display)
	bpy.types.NODE_PT_active_node_properties.remove(NODE_PT_output_path_variable_list)

if __name__ == "__main__":
	register()