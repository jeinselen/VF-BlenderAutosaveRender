bl_info = {
	"name": "VF Autosave Render + Output Variables",
	"author": "John Einselen - Vectorform LLC, based on work by tstscr(florianfelix)",
	"version": (2, 1, 10),
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
	
	# Set estimated render time active to false (must render at least one frame before estimating time remaining)
	bpy.context.scene.autosave_render_settings.estimated_render_time_active = False
	
	# Save start time in seconds as a string to the addon settings
	bpy.context.scene.autosave_render_settings.start_date = str(time.time())
	
	# Track usage of the global serial number in both file output and output nodes to ensure it's only incremented once
	serialUsed = False
	
	# Filter output file path if enabled
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.filter_output_file_path:
		# Save original file path
		bpy.context.scene.autosave_render_settings.output_file_path = filepath = scene.render.filepath
		
		# Check if the serial variable is used
		if '{serial}' in filepath:
			filepath = filepath.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
			serialUsed = True
			
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
					serialUsed = True
				node.base_path = replaceVariables(node.base_path)
				
				# Save and then process the sub-path property of each file slot
				for i, slot in enumerate(node.file_slots):
					node_settings[node.name]["file_slots"][i] = {
						"path": slot.path
					}
					# Replace variables
					if '{serial}' in slot.path:
						slot.path = slot.path.replace("{serial}", format(bpy.context.scene.autosave_render_settings.output_file_serial, '04'))
						serialUsed = True
					slot.path = replaceVariables(slot.path)
					
		# Convert the dictionary to JSON format and save to the plugin preferences for safekeeping while rendering
		bpy.context.scene.autosave_render_settings.output_file_nodes = json.dumps(node_settings)
		
	# Increment the serial number if it was used once or more
	if serialUsed:
		bpy.context.scene.autosave_render_settings.output_file_serial += 1
		
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
		fps_float = str(scene.render.fps / scene.render.fps_base)
		
		# ProRes output
		if bpy.context.scene.autosave_render_settings.autosave_video_prores:
			print('output ProRes video')
			# FFmpeg location
			ffmpeg_command = ffmpeg_location
			# Frame rate
			ffmpeg_command += ' -r ' + fps_float
			# Image sequence pattern
			ffmpeg_command += ' ' + glob_pattern
			# ProRes format
			ffmpeg_command += ' -c:v prores -pix_fmt yuv422p10le'
			# ProRes profile (Proxy, LT, 422 HQ)
			ffmpeg_command += ' -profile:v ' + str(bpy.context.scene.autosave_render_settings.autosave_video_prores_quality)
			# Final output settings
			ffmpeg_command += ' -vendor apl0 -an -sn'
			# Output file path
			ffmpeg_command += ' ' + absolute_path + '.mov'
			
			# Remove any accidental double spaces
			ffmpeg_command = sub(r'\s{2,}', " ", ffmpeg_command)
			print('ProRes command: ' + ffmpeg_command)
			# Run FFmpeg command
			subprocess.call(ffmpeg_command, shell=True)
		
		# MP4 output
		if bpy.context.scene.autosave_render_settings.autosave_video_mp4:
			print('output MP4 video')
			# FFmpeg location
			ffmpeg_command = ffmpeg_location
			# Frame rate
			ffmpeg_command += ' -r ' + fps_float
			# Image sequence pattern
			ffmpeg_command += ' ' + glob_pattern
			# MP4 format
			ffmpeg_command += ' -c:v libx264 -preset slow'
			# MP4 quality (0-51 from highest to lowest quality)
			ffmpeg_command += ' -crf ' + str(bpy.context.scene.autosave_render_settings.autosave_video_mp4_quality)
			# Final output settings
			ffmpeg_command += ' -pix_fmt yuv420p -movflags rtphint'
			# Output file path
			ffmpeg_command += ' ' + absolute_path + '.mp4'
			
			# Remove any accidental double spaces
			ffmpeg_command = sub(r'\s{2,}', " ", ffmpeg_command)
			print('MP4 command: ' + ffmpeg_command)
			# Run FFmpeg command
			subprocess.call(ffmpeg_command, shell=True)
		
		# Custom output
		if bpy.context.scene.autosave_render_settings.autosave_video_custom:
			print('output custom video')
			# FFmpeg location
			ffmpeg_command = ffmpeg_location + ' ' + bpy.context.scene.autosave_render_settings.autosave_video_custom_command
			# Replace variables
			ffmpeg_command = ffmpeg_command.replace("{fps}", fps_float)
			ffmpeg_command = ffmpeg_command.replace("{input}", glob_pattern)
			ffmpeg_command = ffmpeg_command.replace("{output}", absolute_path)
			
			# Remove any accidental double spaces
			ffmpeg_command = sub(r'\s{2,}', " ", ffmpeg_command)
			print('Custom command: ' + ffmpeg_command)
			# Run FFmpeg command
			subprocess.call(ffmpeg_command, shell=True)
	
	# Set video sequence status to false
	bpy.context.scene.autosave_render_settings.autosave_video_sequence = False
	
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
				return {'ERROR'}
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
			return
		
		# Please note that multilayer EXR files are currently unsupported in the Python API - https://developer.blender.org/T71087
		image.save_render(filepath, scene=None) # Might consider using bpy.context.scene if different compression settings are desired per-scene?
		
		# Restore original user settings for render output
		scene.render.image_settings.file_format = original_format
		scene.render.image_settings.color_mode = original_colormode
		scene.render.image_settings.color_depth = original_colordepth
	
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

	# Using "replace" instead of "format" because format fails ungracefully when an exact match isn't found
	# Project variables
	string = string.replace("{project}", os.path.splitext(os.path.basename(bpy.data.filepath))[0])
	string = string.replace("{scene}", bpy.context.scene.name)
	string = string.replace("{collection}", bpy.context.collection.name)
	string = string.replace("{camera}", bpy.context.scene.camera.name)
	string = string.replace("{item}", bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else 'None')
	string = string.replace("{material}", bpy.context.view_layer.objects.active.active_material.name if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.active_material else 'None')
	# Rendering variables
	string = string.replace("{renderengine}", renderEngine)
	string = string.replace("{device}", renderDevice)
	string = string.replace("{samples}", renderSamples)
	string = string.replace("{features}", renderFeatures)
		# {rendertime} is handled elsewhere
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
		default='JPEG')
	
	# FFMPEG output processing
	ffmpeg_processing: bpy.props.BoolProperty(
		name='Autosave videos',
		description='Implements most of the same keywords used in the custom naming scheme in the Output directory',
		default=True)
	ffmpeg_location: bpy.props.StringProperty(
		name="FFmpeg location",
		description="System location where the the FFmpeg command line interface is installed",
		default="/opt/local/bin/ffmpeg",
		maxlen=4096,
		update=lambda self, context: self.update_ffmpeg_location())
	ffmpeg_location_previous: bpy.props.StringProperty(default="")
	ffmpeg_exists: bpy.props.BoolProperty(
		name="FFmpeg exists",
		description='Stores the existance of FFmpeg at the defined system location',
		default=False)
	
	# Validate the ffmpeg location string on value change and plugin registration
	def update_ffmpeg_location(self):
		# Ensure it points at ffmpeg
		if not self.ffmpeg_location.endswith('ffmpeg'):
			self.ffmpeg_location = self.ffmpeg_location + 'ffmpeg'
		# Test if it's a valid path
		if self.ffmpeg_location != self.ffmpeg_location_previous:
			self.ffmpeg_exists = False if which(self.ffmpeg_location) is None else True
			print("FFmpeg status: "+str(self.ffmpeg_exists))
			self.ffmpeg_location_previous = self.ffmpeg_location
	
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
#		grid3.label(text="")
		
		# Location
		grid4 = layout.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		if not self.ffmpeg_processing:
			grid4.active = False
			grid4.enabled = False
		
		# Location entry field
		grid4.prop(self, "ffmpeg_location", text="")
		
		# Location exists success/fail
		box3 = grid4.box()
		if self.ffmpeg_exists:
			box3.label(text="✔︎ location confirmed")
		else:
			box3.label(text="✘ invalid installation path")



###########################################################################
# Individual project settings

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
	
	# FFmpeg image sequence compilation
	autosave_video_sequence: bpy.props.BoolProperty(
		name="Sequence Active",
		description="Indicates if a sequence is being rendering to ensure FFmpeg is enabled only when more than one frame has been rendered",
		default=False)
	autosave_video_prores: bpy.props.BoolProperty(
		name="Enable ProRes Output",
		description="Automatically compiles completed image sequences into a ProRes compressed .mov file",
		default=False)
	autosave_video_prores_quality: bpy.props.EnumProperty(
		name='ProRes Quality',
		description='Video codec used',
		items=[
			('0', 'ProRes Quality Proxy', 'ProResProxy'),
			('1', 'ProRes Quality LT', 'ProResLT'),
			('2', 'ProRes Quality 422', 'ProRes422'),
			('3', 'ProRes Quality HQ', 'ProRes422HQ'),
			],
		default='3')
	autosave_video_mp4: bpy.props.BoolProperty(
		name="Enable MP4 Output",
		description="Automatically compiles completed image sequences into an H.264 compressed .mp4 file",
		default=False)
	autosave_video_mp4_quality: bpy.props.IntProperty(
		name="MP4 Quality",
		description="CRF value where 0 is uncompressed and 51 is the lowest quality possible; 23 is the FFmpeg default but 18 produces better results (closer to visually lossless)",
		default=18,
		step=2,
		soft_min=2,
		soft_max=48,
		min=0,
		max=51)
	autosave_video_custom: bpy.props.BoolProperty(
		name="Enable Custom Output",
		description="Automatically compiles completed image sequences using a custom FFmpeg string",
		default=False)
	autosave_video_custom_command: bpy.props.StringProperty(
		name="Custom FFmpeg Command",
		description="Custom FFmpeg command line string; {input} {fps} {output} variables must be included, but the command path is automatically prepended",
		default='{input} -r {fps} -c:v hevc_videotoolbox -pix_fmt bgra -b:v 1M -alpha_quality 1 -allow_sw 1 -vtag hvc1 {output}_alpha.mov',
		maxlen=4096)
	
	

###########################################################################
# Output Properties panel UI rendering classes

class RENDER_PT_autosave_video(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Autosave Video"
	bl_parent_id = "RENDER_PT_output"
	# bl_options = {'DEFAULT_CLOSED'}

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
	
#	def draw_header(self, context):
#		self.layout.label(text="Autosave Video")
#		if bpy.context.scene.render.image_settings.file_format not in FFMPEG_FORMATS:
#			self.layout.prop(context.scene.autosave_render_settings, 'enable_autosave_video', text='')
		
	def draw(self, context):
		layout = self.layout
		layout.use_property_decorate = False  # No animation
#		layout.use_property_split = True
		
		# Disable inputs if FFmpeg processing is disabled
#		if bpy.context.preferences.addons['VF_autosaveRender'].preferences.ffmpeg_processing:
#			layout.active = False
#			layout.enabled = False
		
		grid = layout.grid_flow(row_major=True, columns=-2, even_columns=True, even_rows=False, align=False)
		
		# ProRes
		grid.prop(context.scene.autosave_render_settings, 'autosave_video_prores')
		options1 = grid.row()
		if not bpy.context.scene.autosave_render_settings.autosave_video_prores:
			options1.active = False
			options1.enabled = False
		options1.prop(context.scene.autosave_render_settings, 'autosave_video_prores_quality', text='')
		
		# MP4
		grid.prop(context.scene.autosave_render_settings, 'autosave_video_mp4')
		options2 = grid.row()
		if not bpy.context.scene.autosave_render_settings.autosave_video_mp4:
			options2.active = False
			options2.enabled = False
		options2.prop(context.scene.autosave_render_settings, 'autosave_video_mp4_quality')
		
		# Custom command string
		grid.prop(context.scene.autosave_render_settings, 'autosave_video_custom')
		options3 = grid.row()
		if not bpy.context.scene.autosave_render_settings.autosave_video_custom:
			options3.active = False
			options3.enabled = False
		options3.prop(context.scene.autosave_render_settings, 'autosave_video_custom_command', text='')
		
		# Custom command feedback
#		custom_feedback = layout.box()
#		custom_feedback.label(text="Custom string feedback goes here")

class RENDER_PT_autosave_render(bpy.types.Panel):
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "render"
	bl_label = "Autosave Render"
	bl_parent_id = "RENDER_PT_output"
	# bl_options = {'DEFAULT_CLOSED'}
	
	# Check for engine compatibility
	# compatible_render_engines = {'BLENDER_RENDER', 'BLENDER_OPENGL', 'BLENDER_WORKBENCH', 'BLENDER_EEVEE', 'CYCLES', 'RPR', 'LUXCORE'}
	# @classmethod
	# def poll(cls, context):
		# return (context.engine in cls.compatible_render_engines)
	
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
#		print(context.window_manager.clipboard)
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
# Display estimated render time remaining in the Image viewer
		
def estimated_render_time(self, context):
	if bpy.context.preferences.addons['VF_autosaveRender'].preferences.remaining_render_time and bpy.context.scene.autosave_render_settings.estimated_render_time_active:
		self.layout.separator()
		box = self.layout.box()
		box.label(text="  Estimated Time Remaining: " + bpy.context.scene.autosave_render_settings.estimated_render_time_value + "")

###########################################################################
# Addon registration functions

classes = (AutosaveRenderPreferences, AutosaveRenderSettings, RENDER_PT_autosave_video, RENDER_PT_autosave_render, AutosaveRenderVariablePopup, AutosaveRenderVariableCopy)

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
	bpy.types.IMAGE_MT_editor_menus.append(estimated_render_time)
	# Variable info popup
	bpy.types.RENDER_PT_output.prepend(RENDER_PT_output_path_variable_list)
	bpy.types.RENDER_PT_output.append(RENDER_PT_total_render_time_display)
	bpy.types.NODE_PT_active_node_properties.prepend(NODE_PT_output_path_variable_list)
	## Update FFmpeg location
	bpy.context.preferences.addons[__name__].preferences.update_ffmpeg_location()

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
	bpy.types.IMAGE_MT_editor_menus.remove(estimated_render_time)
	# Variable info popup
	bpy.types.RENDER_PT_output.remove(RENDER_PT_output_path_variable_list)
	bpy.types.RENDER_PT_output.remove(RENDER_PT_total_render_time_display)
	bpy.types.NODE_PT_active_node_properties.remove(NODE_PT_output_path_variable_list)

if __name__ == "__main__":
	register()