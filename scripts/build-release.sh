#!/bin/bash
# Velotric E-Bike HACS Release Builder
# Usage: ./build-release.sh [version]

set -e

VERSION="${1:-dev}"
SOURCE_DIR="."  # Project root (contains custom_components/ and README.md, hacs.json)
OUTPUT_DIR="releases"
ZIP_NAME="ha-velotric.zip"

echo "Building Velotric E-Bike integration release v${VERSION}..."

# Clean previous builds
rm -f "${OUTPUT_DIR}"/*.zip
rm -f "${OUTPUT_DIR}"/*.sha256

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Build using the python packaging script
python3 scripts/package.py --source . --output "${OUTPUT_DIR}/${ZIP_NAME}"

# Verify the archive
python3 scripts/package.py --source . --verify-archive "${OUTPUT_DIR}/${ZIP_NAME}"

echo "Release built: ${OUTPUT_DIR}/${ZIP_NAME}"
echo "SHA256: $(cat "${OUTPUT_DIR}/${ZIP_NAME}.sha256")"
