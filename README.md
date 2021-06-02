# VF-BlenderAutoSaveRender
Automatically saves a numbered or dated image after every render. This Blender Addon is designed to make test renders easier to review, saving what would otherwise be lost when quitting the app. It's also good for showing render progression after a project is complete, a timelapse of sorts.

## Installation and usage
- Download the .py file
- Open Blender preferences and navigate to the "Add-ons" tab
- Install the addon
- Enable the addon
- Open up the Render Output settings to find the Auto Save Render sub-panel and enable it

![screenshot of the Blender render output user interface with the addon installed](images/screenshot.jpg)

## Settings

### Autosave Location

- Select a specific directory such as `/project/renders/autosave/` to automatically save all renders to the same location
- Leave a single forward slash `/` to generate a folder with the same name as the Blender file (a collection of Blender projects would each have matching folders alongside them)

### File Name

- `Project Name + Serial Number`
  - This uses the name of the Blender file and a generated serial number (it will detect any existing files in the autosave location and increment by one)
- `Project Name + Date & Time`
  - This uses the name of the blender file and the local date and time (formatted YYYY-MM-DD HH-MM-SS using 24 hour time)

![screenshot of the Blender render output user interface with the addon installed](images/screenshot2.jpg)
- `Custom String`
  - This uses pattern replacement to allow for entirely unique file naming patterns
  - These are the supported variables:
    - `{project}` = the name of the Blender file
    - `{item}` = active item (if no item is selected or active, this will return "None")
    - `{camera}` = render camera (independent of selection or active status)
    - `{frame}` = current frame padded to four digits
    - `{renderengine}` = internal name of the current rendering engine
    - `{rendertime}` = time spent rendering (this is calculated within the script and may not exactly match the render metadata since it's not included in the Python API)
    - `{date}` = current date in YYYY-MM-DD format
    - `{time}` = current time in HH-MM-SS format (using a 24 hour clock)
    - `{serial}` = automatically incremented serial number padded to 4 digits (_this must go at the end of the string with no character afterward_, otherwise the script cannot find the correct serial number in the file listing)
  - **Warning**: using a custom string may result in data loss by either overwriting or failing to save identical file names. For example, if the date and time variables are not included, or the serial number is not placed at the very end of the pattern.

### File Format

- `Project Setting` will use the same format as set in the Render Output panel
- `PNG`
- `JPEG`
- `OpenEXR MultiLayer`

## Notes

Auto Save Render depends on the Blender file having been saved at least once, otherwise there is no project name or directory to work from.

When rendering animations this addon will only automatically save the final frame to prevent unnecessary duplication (animations should already be saved automatically). It may still be useful to leave the plugin enabled, however, since that final frame will include the entire time spent rendering that animation (if you're using the custom string), meaning you could calculate the total time spent rendering a project simply from the files saved by this addon.