import zipfile
import os
import re

# === CONFIGURATION ===
zip_path = r"C:\Users\Quadrant\Downloads\leadership (3)\leadership\\Madhavi Gundavajyala Director – Delivery & Client Relations-LD-28.zip"
extract_dir = r"C:\Users\Quadrant\Downloads\leadership (3)"
rename_dir = os.path.join(extract_dir, "leadership")

# === STEP 1: Extract ZIP ===
os.makedirs(rename_dir, exist_ok=True)
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall(rename_dir)

print("✅ Extraction complete!")

# === STEP 2: Normalize file names ===
def normalize_filename(filename):
    name, ext = os.path.splitext(filename)
    # Remove unwanted symbols, keep only letters, numbers, spaces
    name = re.sub(r"[^a-zA-Z0-9\s]", "", name)
    # Convert multiple spaces to one
    name = re.sub(r"\s+", " ", name.strip())
    # Convert to lowercase, replace spaces with hyphens
    name = name.lower().replace(" ", "-")
    return f"{name}{ext.lower()}"

print("\n🔄 Renaming files...")
for file in os.listdir(rename_dir):
    old_path = os.path.join(rename_dir, file)
    if os.path.isfile(old_path):
        new_name = normalize_filename(file)
        new_path = os.path.join(rename_dir, new_name)
        os.rename(old_path, new_path)
        print(f"✔ {file} → {new_name}")

# === STEP 3: Generate .env lines ===
print("\n📄 .env lines:\n")
for file in os.listdir(rename_dir):
    if os.path.isfile(os.path.join(rename_dir, file)):
        base_name, _ = os.path.splitext(file)
        var_name = "LEADERSHIP_" + base_name.replace("-", "_").upper() + "_URL"
        print(f"{var_name}=http://localhost:8080/assets/{file}")

print("\n🎉 Done! Files renamed and .env lines generated.")
