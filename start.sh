#!/bin/bash
read -p "Do you want to edit the .env file? (y/n): " choice

if [ "$choice" == "y" ] || [ "$choice" == "Y" ]; then
    nano .env
    echo "Continuing..."
else
    echo "Continuing without editing .env file..."
fi
python3 -m pip install -r requirements.txt
python3 start.py