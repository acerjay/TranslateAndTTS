import zipfile
import os
import re
import shutil

def modify_gridset(gridset_path, LocalAppPath):
	temp_dir = 'temp_gridset'
	os.makedirs(temp_dir, exist_ok=True)
	
	with zipfile.ZipFile(gridset_path, 'r') as zip_ref:
		zip_ref.extractall(temp_dir)
	
	for foldername, _, filenames in os.walk(temp_dir):
		for filename in filenames:
			if filename.endswith('.xml'):
				xml_path = os.path.join(foldername, filename)
				
				with open(xml_path, 'r') as f:
					filedata = f.read()
				
				local_app_data_path = os.environ.get('LOCALAPPDATA', '')
				full_path_to_exe = os.path.join(local_app_data_path, 'Programs', 'Ace Centre', 'TranslateAndTTS', 'translatepb.exe')
				full_path_to_exe_escaped = full_path_to_exe.replace('\\', '\\\\')
				new_data = re.sub('%FILEPATHTOREPLACE%', full_path_to_exe_escaped, filedata)
							
				with open(xml_path, 'w') as f:
					f.write(new_data)
		
	new_gridset_dir = os.path.join(LocalAppPath, 'TranslateAndTTS', 'Example AAC Helper Pages')
	new_gridset_path = os.path.join(new_gridset_dir, 'AAC Helper Tool Demo.gridset')
	
	os.makedirs(new_gridset_dir, exist_ok=True)
	
	with zipfile.ZipFile(new_gridset_path, 'w') as zipf:
		for root, _, files in os.walk(temp_dir):
			for file in files:
				zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), temp_dir))
	
	# Delete the temp directory after creating the modified .gridset
	shutil.rmtree(temp_dir)
	os.remove(gridset_path)

	# Create a .bat file on the Desktop to act as a shortcut
	desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
	bat_file = os.path.join(desktop, "Open Example AAC Helper Pages.bat")
	
	with open(bat_file, 'w') as f:
		f.write(f'start "" "{new_gridset_dir}"')

if __name__ == "__main__":
	app_data_path = os.environ.get('APPDATA', '')  # Changed to APPDATA
	gridset_location = os.path.join(app_data_path, 'TranslateAndTTS', 'TranslateAndTTS DemoGridset.gridset')  # Updated path
	
	# Assuming the original gridset is located at 'TranslateAndTTS DemoGridset.gridset' within the APPDATA folder
	modify_gridset(gridset_location, app_data_path)