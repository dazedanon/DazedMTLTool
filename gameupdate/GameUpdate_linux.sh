#!/bin/bash

# Enable error handling
set -e

# Copy patch.sh to a new file in gameupdate
cp "gameupdate/patch.sh" "gameupdate/patch2.sh"

# Run the new file
bash "gameupdate/patch2.sh"

# Delete the new file
rm "gameupdate/patch2.sh"
