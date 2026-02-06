#!/usr/bin/env python3.13
import asyncio
import logging
import os
import sys
import tempfile
import hashlib
import requests
from pathlib import Path

logger=logging.getLogger(__name__)

GITHUB_REPO="frenchtoblerone54/ghostwire"
CHECK_INTERVAL=300

class Updater:
    def __init__(self,component_name):
        self.component_name=component_name
        self.current_version=self.get_current_version()
        self.update_url=f"https://github.com/{GITHUB_REPO}/releases/latest/download/ghostwire-{component_name}"
        self.check_url=f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    def get_current_version(self):
        script_path=Path(sys.argv[0])
        if script_path.name.startswith(f"ghostwire-{self.component_name}"):
            return "v0.2.3"
        return "dev"

    async def check_for_update(self):
        try:
            response=requests.get(self.check_url,timeout=10)
            if response.status_code!=200:
                logger.warning(f"Failed to check for updates: HTTP {response.status_code}")
                return None
            data=response.json()
            latest_version=data.get("tag_name")
            if not latest_version:
                logger.warning("No tag_name in release data")
                return None
            if latest_version!=self.current_version:
                logger.info(f"New version available: {latest_version} (current: {self.current_version})")
                return latest_version
            logger.debug(f"Already up to date: {self.current_version}")
            return None
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            return None

    def verify_checksum(self,binary_path,expected_checksum):
        sha256_hash=hashlib.sha256()
        with open(binary_path,"rb") as f:
            for chunk in iter(lambda:f.read(4096),b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()==expected_checksum

    async def download_update(self,new_version):
        try:
            binary_url=self.update_url
            checksum_url=f"{binary_url}.sha256"
            logger.info(f"Downloading update from {binary_url}")
            tmpdir="/tmp/ghostwire-update"
            os.makedirs(tmpdir,exist_ok=True)
            binary_path=os.path.join(tmpdir,f"ghostwire-{self.component_name}")
            checksum_path=os.path.join(tmpdir,f"ghostwire-{self.component_name}.sha256")
            response=requests.get(binary_url,timeout=30,stream=True)
            if response.status_code!=200:
                logger.error(f"Failed to download binary: HTTP {response.status_code}")
                return False
            with open(binary_path,"wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            os.chmod(binary_path,0o755)
            response=requests.get(checksum_url,timeout=10)
            if response.status_code==200:
                with open(checksum_path,"w") as f:
                    f.write(response.text.strip())
            logger.info(f"Downloaded {new_version}, creating update marker...")
            marker_path=os.path.join(tmpdir,"update.marker")
            with open(marker_path,"w") as f:
                f.write(new_version)
            logger.info("Update ready. Run: sudo /usr/local/bin/install-update.sh to apply")
            return True
        except Exception as e:
            logger.error(f"Error downloading update: {e}",exc_info=True)
            return False

    async def update_loop(self,shutdown_event):
        logger.info(f"Auto-update checker started (current version: {self.current_version})")
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(CHECK_INTERVAL)
                if shutdown_event.is_set():
                    break
                new_version=await self.check_for_update()
                if new_version:
                    logger.info(f"Updating to {new_version}...")
                    success=await self.download_update(new_version)
                    if success:
                        logger.info("Update complete, shutting down for systemd restart...")
                        shutdown_event.set()
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in update loop: {e}")
