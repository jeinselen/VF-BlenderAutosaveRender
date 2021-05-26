# VF-BlenderAutoSaveRender
Automatically saves a numbered or dated image after every render. This Blender Addon is designed to make test renders easier to review, saving what would otherwise be lost when quitting the app. It's also good for showing render progression after a project is complete, a timelapse of sorts.

### Installation and usage:
- Download the .py file
- Open up Blender preferences
- Install the addon
- Enable the addon
- Open up the Render Output settings to find the Auto Save Render sub-panel and enable it

![screenshot of the Blender render output user interface with the addon installed](images/screenshot.jpg)

### Settings:
- Custom Save Directory
  - Leave a single forward slash `/` to use an auto-generated folder with the same name as the current project
  - Select a specific directory to save all files to the same location
- Camera Name
  - Includes the name of the currently active camera in the output file name
  - _Note: the file name always starts with the same name as the project, regardless of these checkboxes_
- Frame Number
  - Includes the currently active frame padded to 5 digits
- Render Engine
  - Includes the internal name of the currently active render engine
- Render Time
  - Calculates the time spent rendering and includes it in the file name
  - _Note: this addon will only save the final frame during animation sequences to prevent unnecessary duplication (animations should be saved already), but the render time will reflect how long it took to complete the entire animation so if you want to calculate the total time spent rendering tests and animations for a project, you can use these numbers_
  - _Note: the calculated render time may vary by 0.01 second from the time recorded by Blender due to Python API limitations_
- File Numbering
  - A unique number is always included to prevent overwriting previous renders, with either a _Serial Number_ padded to 4 digits, or a _Time Stamp_ using the format `YYYY_MM_DD-hour_minute_second`
- File Format
  - This can be set to use the same format as selected in the Blender Output panel, or override this project setting with PNG, JPEG, or OpenEXR MultiLayer output
