#!/usr/bin/env python3.13
import asyncio
import logging
import os
import sys
import hashlib
import json
import aiohttp
from pathlib import Path

logger=logging.getLogger(__name__)

GITHUB_REPO="frenchtoblerone54/ghostwire"

class Updater:
    def __init__(self,component_name,check_interval=300,check_on_startup=True,http_proxy="",https_proxy=""):
        self.component_name=component_name
        self.check_interval=check_interval
        self.check_on_startup=check_on_startup
        self.http_proxy=http_proxy
        self.https_proxy=https_proxy
        self.current_version=self.get_current_version()
        self.update_url=f"https://github.com/{GITHUB_REPO}/releases/latest/download/ghostwire-{component_name}"
        self.check_url=f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    def get_current_version(self):
        script_path=Path(sys.argv[0])
        if script_path.name.startswith(f"ghostwire-{self.component_name}"):
            return "v0.11.6"
        return "dev"

    async def http_get(self,url,timeout):
        timeout_config=aiohttp.ClientTimeout(total=timeout)
        proxy=self.https_proxy if url.startswith("https://") else self.http_proxy
        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            async with session.get(url,proxy=proxy if proxy else None) as response:
                status=response.status
                body=await response.read()
                return status,body

    async def http_download(self,url,output_path,timeout):
        timeout_config=aiohttp.ClientTimeout(total=timeout)
        proxy=self.https_proxy if url.startswith("https://") else self.http_proxy
        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            async with session.get(url,proxy=proxy if proxy else None) as response:
                if response.status!=200:
                    return response.status
                with open(output_path,"wb") as f:
                    async for chunk in response.content.iter_chunked(65536):
                        f.write(chunk)
                return 200

    async def check_for_update(self):
        try:
            status,body=await self.http_get(self.check_url,10)
            if status!=200:
                logger.warning(f"Failed to check for updates: HTTP {status}")
                return None
            data={}
            try:
                data=json.loads(body.decode())
            except Exception:
                logger.warning("Failed to parse update response")
                return None
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
            tmpdir=f"/tmp/ghostwire-update-{self.component_name}-{os.getpid()}"
            os.makedirs(tmpdir,exist_ok=True)
            binary_path=os.path.join(tmpdir,f"ghostwire-{self.component_name}")
            status=await self.http_download(binary_url,binary_path,300)
            if status!=200:
                logger.error(f"Failed to download binary: HTTP {status}")
                return False
            os.chmod(binary_path,0o755)
            checksum_status,checksum_body=await self.http_get(checksum_url,30)
            if checksum_status==200:
                checksum_content=checksum_body.decode().strip()
                parts=checksum_content.split()
                expected_checksum=parts[0] if parts else checksum_content
                if not self.verify_checksum(binary_path,expected_checksum):
                    logger.error("Checksum verification failed")
                    return False
                logger.info("Checksum verified")
            else:
                logger.warning("Could not download checksum, skipping verification")
            executable_path=sys.argv[0]
            logger.info(f"Successfully updated to {new_version}, restarting...")
            os.execv("/bin/bash",["/bin/bash","-c",f"sleep 0.5; mv '{executable_path}' '{executable_path}.old' 2>/dev/null; mv '{binary_path}' '{executable_path}'; exec '{executable_path}' "+" ".join(sys.argv[1:])])
            return True
        except Exception as e:
            logger.error(f"Error downloading update: {e}",exc_info=True)
            return False

    async def update_loop(self,shutdown_event):
        logger.info(f"Auto-update checker started (interval: {self.check_interval}s, current version: {self.current_version})")
        if self.check_on_startup:
            logger.info("Checking for updates on startup...")
            new_version=await self.check_for_update()
            if new_version:
                logger.info(f"Updating to {new_version}...")
                success=await self.download_update(new_version)
                if success:
                    logger.info("Update complete, shutting down for systemd restart...")
                    return
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(self.check_interval)
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
