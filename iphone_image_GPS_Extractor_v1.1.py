# This application has the role of processing image files taken outdoors with an iPhone.
#  The exif data is copied from the HEIC file.
#  Images are converted from HEIC to .jpg using FFmpeg.
#  The exif data is attached to the JPG.
#  Images are stored in a subfolder called converted images. 
#  EXIF data attached to the .jpg files is reviewed for the presenmce of GPS data. If data is present it is
#  copied and placed into a .csv file which can then be opened in excel.
#  Developed by Slade Beard, Ecothought Pty Ltd ABN 15 125 372 821 with the assistance of ChatGPT and Copilot.
import os
import pandas as pd
from PIL import Image, ExifTags
from PIL.ExifTags import TAGS, GPSTAGS
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pillow_heif
import subprocess
import json
from fractions import Fraction
import math

# Ensure HEIC support is enabled
pillow_heif.register_heif_opener()

# Global variables
ffmpeg_available = False
exiftool_available = False
settings_file = "settings.json"
exiftool_path = "exiftool"  # Default to system PATH
tool_status_label = None  # Reference for tool status

# Load settings (ExifTool path)
def load_settings():
    global exiftool_path
    if os.path.exists(settings_file):
        with open(settings_file, "r") as f:
            settings = json.load(f)
            exiftool_path = settings.get("exiftool_path", "exiftool")

# Save settings (ExifTool path)
def save_settings():
    global exiftool_path
    with open(settings_file, "w") as f:
        json.dump({"exiftool_path": exiftool_path}, f)

# Initialize settings
load_settings()

# Check that Exiftool aznd FFmpeg are available and update the status in the GUI

# Check if FFmpeg is available
def check_ffmpeg():
    global ffmpeg_available
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        ffmpeg_available = True
    except FileNotFoundError:
        ffmpeg_available = False

# Check if ExifTool is available
def check_exiftool():
    global exiftool_available
    try:
        result = subprocess.run([exiftool_path, "-ver"], capture_output=True, text=True)
        exiftool_available = result.returncode == 0
    except FileNotFoundError:
        exiftool_available = False

# Function to update tool status in GUI
def update_tool_status():
    global tool_status_label
    status_text = f"FFmpeg: {'Available' if ffmpeg_available else 'Not Available'} | ExifTool: {'Available' if exiftool_available else 'Not Available'}"
    tool_status_label.config(text=status_text, fg="green" if ffmpeg_available and exiftool_available else "red")

# Function to set ExifTool path through a file dialog
def set_exiftool_path():
    global exiftool_path
    path = filedialog.askopenfilename(title="Select ExifTool Executable", filetypes=[("Executable Files", "*.exe")])
    if path:
        exiftool_path = path
        save_settings()
        check_exiftool()
        update_tool_status()

# Functions to convert DMS to Decimal Degrees and to UTM coordinates

# Convert Latitude and Longitude to UTM
def latlon_to_utm(latitude, longitude):
    zone_number = int((longitude + 180) / 6) + 1
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)
    lon_origin = (zone_number - 1) * 6 - 180 + 3
    lon_origin_rad = math.radians(lon_origin)
    a = 6378137.0
    e = 0.081819191
    n = a / math.sqrt(1 - e ** 2 * math.sin(lat_rad) ** 2)
    t = math.tan(lat_rad) ** 2
    c = (e ** 2) / (1 - e ** 2) * math.cos(lat_rad) ** 2
    a_ = (lon_rad - lon_origin_rad) * math.cos(lat_rad)
    easting = (n * (a_ + (1 - t + c) * a_ ** 3 / 6) + 500000.0)
    northing = (n * (math.tan(lat_rad) / 2 + (5 - t + 9 * c) * a_ ** 4 / 24))
    if latitude < 0:
        northing += 10000000.0
    return easting, northing

# Enhanced Function to Convert DMS (Degrees, Minutes, Seconds) to Decimal
def convert_to_decimal(value):
    
    if isinstance(value, tuple):
        degrees = convert_ifdrational(value[0])
        minutes = convert_ifdrational(value[1])
        seconds = convert_ifdrational(value[2])
        return degrees + (minutes / 60.0) + (seconds / 3600.0)
    else:
        return convert_ifdrational(value)

# Function to safely convert IFDRational or fraction values
def convert_ifdrational(value):
    """Safely convert IFDRational values to float."""
    if isinstance(value, Fraction):
        return float(value)
    elif hasattr(value, 'numerator') and hasattr(value, 'denominator'):
        return value.numerator / value.denominator
    elif isinstance(value, tuple) and len(value) == 2:
        return value[0] / value[1]
    else:
        return float(value)

# Function to extract GPS data in decimal format
def extract_gps_info(exif_data):
    if not exif_data:
        return None

    gps_info = {}
    for tag, value in exif_data.items():
        tag_name = TAGS.get(tag, tag)
        if tag_name == "GPSInfo":
            for gps_tag in value:
                sub_tag = GPSTAGS.get(gps_tag, gps_tag)
                gps_info[sub_tag] = value[gps_tag]

    if "GPSLatitude" in gps_info and "GPSLongitude" in gps_info:
        latitude = convert_to_decimal(gps_info["GPSLatitude"])
        longitude = convert_to_decimal(gps_info["GPSLongitude"])

        # Apply reference (S or N, W or E)
        lat_ref = gps_info.get("GPSLatitudeRef", "N")
        lon_ref = gps_info.get("GPSLongitudeRef", "E")

        if lat_ref == "S":
            latitude = -latitude
        if lon_ref == "W":
            longitude = -longitude
-       easting, northing = latlon_to_utm(latitude, longitude)
        return {
            "Latitude": round(latitude, 6),
                "Longitude": round(longitude, 6),
                "Easting": round(easting, 2),
                "Northing": round(northing, 2)
        }
    return None

# Function to process folder
def process_folder(folder_path, status_label, progress_bar):
    if not folder_path or not os.path.isdir(folder_path):
        messagebox.showwarning("Warning", "Please select a valid folder.")
        status_label.config(text="No valid folder selected.")
        return

    debug_log = os.path.join(folder_path, "debug_log.txt")
    converted_folder = os.path.join(folder_path, 'converted_images')
    os.makedirs(converted_folder, exist_ok=True)

    gps_data_list = []
    files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.heic', '.HEIC', '.jpg', '.jpeg'))]
    total_files = len(files)
    processed_files = 0

    with open(debug_log, 'w') as debug_file:
        debug_file.write(f"Debug Log for Image Processing\nSelected Folder: {folder_path}\n\n")

        for file in files:
            image_path = os.path.join(folder_path, file)
            jpeg_path = os.path.join(converted_folder, os.path.splitext(file)[0] + '.jpg')

            if file.lower().endswith('.heic'):
                heif_image = pillow_heif.open_heif(image_path)
                image = heif_image.to_pillow().convert("RGB")
                image.save(jpeg_path, "JPEG", exif=heif_image.info.get('exif'))

            image = Image.open(jpeg_path)
            exif_data = image._getexif() or image.getexif()
            if exif_data:
                gps_info = extract_gps_info(exif_data)
                if gps_info:
                    gps_data_list.append({"Filename": file, **gps_info})
                    debug_file.write(f"GPS Data for {file}: {gps_info}\n")

            processed_files += 1
            progress_bar['value'] = int((processed_files / total_files) * 100)
            status_label.config(text=f"Processing {processed_files} of {total_files} images")
            status_label.update()

        if gps_data_list:
            gps_csv = os.path.join(folder_path, "extracted_gps_data.csv")
            pd.DataFrame(gps_data_list).to_csv(gps_csv, index=False)

    messagebox.showinfo("Processing Complete", f"Processed {processed_files} images.")

# Function to start GUI
def start_gui():
    global tool_status_label

    root = tk.Tk()
    root.title("iPhone Image Metadata Extractor")

    check_ffmpeg()
    check_exiftool()

    tool_status_label = tk.Label(root, text="Checking tool status...")
    tool_status_label.pack(pady=5)
    update_tool_status()

    folder_label = tk.Label(root, text="Select Folder:")
    folder_label.pack(pady=5)

    folder_entry = tk.Entry(root, width=40)
    folder_entry.pack(pady=5)

    def browse_folder():
        selected_folder = filedialog.askdirectory()
        folder_entry.delete(0, tk.END)
        folder_entry.insert(0, selected_folder)

    tk.Button(root, text="Browse", command=browse_folder).pack(pady=5)
    tk.Button(root, text="Set ExifTool Path", command=set_exiftool_path).pack(pady=5)

    status_label = tk.Label(root, text="Ready")
    status_label.pack(pady=5)

    progress_bar = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
    progress_bar.pack(pady=5)

    def start_processing():
        folder_path = folder_entry.get()
        if not folder_path:
            messagebox.showwarning("Warning", "Please select a valid folder.")
            return

        status_label.config(text="Processing started...")
        process_folder(folder_path, status_label, progress_bar)

    tk.Button(root, text="Proceed", command=start_processing).pack(pady=5)
    tk.Button(root, text="Exit", command=root.quit).pack(pady=5)

    root.geometry("400x500")
    root.mainloop()
start_gui()



