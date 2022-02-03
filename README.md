# VF Auto Save Render

Automatically saves a numbered or dated image after every render and can extend the Blender output path with dynamic variables. This Blender Add-on is designed to make test renders easier to review, saving what would otherwise be lost when quitting the app. It's also good for creating a progression timelapse after a project is complete, or naming rendered files with the currently selected object or other custom settings.

![screenshot of Blender's Render Output user interface with the add-on installed](images/screenshot.png)

## Installation and usage
- Download [VF_autoSaveRender.py](https://raw.githubusercontent.com/jeinselenVF/VF-BlenderAutoSaveRender/main/VF_autoSaveRender.py)
- Open Blender Preferences and navigate to the "Add-ons" tab
- Install and enable the Add-on
- It will be enabled by default in the Render Output panel, where you can customise the automatic file output settings

## Add-on Preferences

![screenshot of the add-on's user preferences in the Blender Preferences Add-ons panel](images/screenshot1.png)

Add-on preferences are found in the plugin listing in the Add-on panel of the user preferences.

- `Show Total Render Time` toggles the "total time spent rendering" display in the project settings (turned off by default)
- `Total Render Time` shows the raw value in seconds in case you need to manually override the project-specific value
- `Process Output File Path` toggles filtering of the Blender file output name for specific variables (turned off by default)

## Project Settings

![screenshot of the add-on's project settings panel with customised auto save settings](images/screenshot2.png)

Project settings are found at the bottom of the Render Output panel and are unique per-project. The Add-on can be disabled here by unchecking `Auto Save Render` (turned on by default).

### Autosave Location

- Leave a single forward slash `/` to automatically generate a folder with the same name and in the same directory as the Blender project
- Or select a specific directory such as `/project/renders/autosave/` to automatically save all renders to the same location

### File Name

- `Project Name + Serial Number`
  - This uses the name of the Blender file and a generated serial number (it will detect any existing files in the autosave location and increment by one)
- `Project Name + Date & Time`
  - This uses the name of the blender file and the local date and time (formatted YYYY-MM-DD HH-MM-SS using 24 hour time)
- `Project Name + Render Engine + Render Time`
  - This uses the name of the blender file, the name of the render engine, and the time it took to render
  - When a sequence is rendered, only the final frame will be saved and this value will be the total sequence render time, not the per-frame render time
- `Custom String`
  - This uses pattern replacement to allow for entirely unique file naming patterns
  - Supported variables:
    - `{project}` = the name of the Blender file
    - `{scene}` = current scene being rendered (if multiple scenes are used in the compositing tab, only the currently selected scene name will be used)
    - `{camera}` = render camera (independent of selection or active status)
    - `{item}` = active item (if no item is selected or active, this will return "None")
    - `{frame}` = current frame number (padded to four digits)
    - `{renderengine}` = name of the current rendering engine (uses the internal Blender identifier)
    - `{rendertime}` = time spent rendering (this is calculated within the script and may not _exactly_ match the render metadata, which is unavailable in the Python API)
    - `{date}` = current date in YYYY-MM-DD format
    - `{time}` = current time in HH-MM-SS format (using a 24 hour clock)
    - `{serial}` = automatically incremented serial number padded to 4 digits
- `Serial Number`
  - This input field only appears if the text `{serial}` appears in the `Custom String` setting, and automatically increments every time a render is saved (easily overwritten if you need to reset the count at any time)

_Warning_: using a custom string may result in overwriting files or failing to save if the generated name is not unique (for example, if date and time or serial number variables are not included). The creator of this plugin accepts no responsibility for data loss.

### File Format

- `Project Setting` will use the same format as set in the Render Output panel
- `PNG`
- `JPEG`
- `OpenEXR MultiLayer`

File formats will use whatever compression preferences habe been set in the project. If you want to render animations using the PNG format, but save previews using JPG with a specific compression level, temporarily choose JPG as your Blender output format and customise the settings, then switch back to PNG. When Auto Save Render outputs the preview file, it'll use the (now invisible) default JPG settings.

### Total Time Spent Rendering

- This tracks the total number of hours, minutes, and seconds spent rendering the current project, and the output panel display can be turned on in the Add-on Preferences (see above)

### Render Output Variables

![screenshot of the add-on's project settings panel with the output variables](images/screenshot3.png)

If enabled in the add-on preferences, this extends the native Blender output path with many of the `Custom String` variables listed above: `{project}` `{scene}` `{camera}` `{item}` `{renderengine}` `{date}` `{time}` `{serial}`

This works well for automatic naming of animations, since the variables are processed at rendering start and will remain unchanged until the render is canceled or completed. Starting a new render will update the date, time, serial number, or any other variables that might have been changed.

## Notes

- Auto Save Render depends on the Blender file having been saved at least once in order to save images, otherwise there is no project name or directory for the Add-on to work with
- Only the final frame will be atuo saved when rendering sequences, preventing mass dupliation but still allowing for total render time to be saved in the file name (depending on settings)
- Total render time will continue to increment even when auto file saving is toggled off in the output panel
- Total render time will _not_ increment when rendering files from the command line, since it depends on being saved within the project file (and rendering from the command line typically doesn't save the project file after rendering finishes)