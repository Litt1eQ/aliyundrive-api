# -*- coding: utf-8 -*-
# @Author  : __LittleQ__
# @FileName: index.py.py

import hashlib
import os
import sys
from configparser import ConfigParser

from typing import Union, List

import requests
from tqdm import tqdm

SETTINGS_CONFIG_PATH = './config.ini'


class ChunksIter:

    def __init__(self, file, total_size, chunk_size=1024 * 1024):
        self.file = file
        self.total_size = total_size
        self.chunk_size = chunk_size

    def __iter__(self):
        return self

    def __next__(self):
        data = self.file.read(self.chunk_size)
        if not data:
            raise StopIteration
        return data

    def __len__(self):
        return self.total_size


class AliyunDriveApi:
    base_api = 'https://api.aliyundrive.com/v2/'

    def __init__(self):
        config = ConfigParser()
        config.read_file(open(SETTINGS_CONFIG_PATH))
        self.config = config
        if not config.has_section('account'):
            print('Must add account section to config.ini')
            exit(-1)
        if not config.has_option('account', 'access_token'):
            print('Must add access_token option to account section to config.ini')
            exit(-1)
        if not config.has_option('account', 'refresh_token'):
            print('Must add refresh_token option to account section to config.ini')
            exit(-1)

        self.access_token = config.get('account', 'access_token')
        self.refresh_token = config.get('account', 'refresh_token')
        self.drive_id = config.get('account', 'drive_id')

        self.headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": self.access_token,
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.aliyundrive.com",
            "referer": "https://www.aliyundrive.com/",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.128 Safari/537.36"
        }

        # 如果没有配置drive_id, 首先请求一下drive_id
        if not self.drive_id:
            self.get_user_info()

        self.root = []

    def do_refresh_token(self):
        data = {
            "refresh_token": self.refresh_token
        }
        res = requests.post("https://websv.aliyundrive.com/token/refresh", headers={
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.aliyundrive.com",
            "referer": "https://www.aliyundrive.com/",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.128 Safari/537.36"
        }, json=data).json()

        self.access_token = res.get('access_token')
        self.headers['authorization'] = self.access_token
        self.config.set('account', 'access_token', self.access_token)
        self.config.write(open('./config.ini', 'w'))
        return True

    def get_user_info(self):
        res = requests.post(self.base_api + 'user/get', headers=self.headers, json={}).json()
        if res.get('code') == 'AccessTokenInvalid':
            if self.do_refresh_token():
                return self.get_user_info()
            else:
                print('Refresh Token Failed!')
                exit(-1)
        self.drive_id = res.get('default_drive_id')
        self.config.set('account', 'drive_id', res.get('default_drive_id'))
        self.config.write(open(SETTINGS_CONFIG_PATH, 'w'))
        return res

    def get_list(self, parent_file_id='root'):
        data = {
            "drive_id": self.drive_id,
            "parent_file_id": parent_file_id,
            "limit": 100,
            "all": False,
            "image_thumbnail_process": "image/resize,w_160/format,jpeg",
            "image_url_process": "image/resize,w_1920/format,jpeg",
            "video_thumbnail_process": "video/snapshot,t_0,f_jpg,ar_auto,w_300",
            "fields": "*",
            "order_by": "updated_at",
            "order_direction": "DESC"
        }
        res = requests.post(self.base_api + 'file/list', headers=self.headers, json=data).json()
        if res.get('code') == 'AccessTokenInvalid':
            if self.do_refresh_token():
                return self.get_list(parent_file_id)
            else:
                print('Refresh Token Failed!')
                exit(-1)
        self.root += res.get('items')
        return res

    def _get_parent_file_id(self, parent: str) -> str:
        """
        获取父文件夹ID
        :param parent: parent格式 xxx/xxx/xxx
        :return:
        """
        if not parent:
            return 'root'

        dirs = parent.split('/')
        parent_file_name = dirs[0]
        parent_file_id = 'root'

        for item in self.root:
            if item['name'] == parent_file_name:
                parent_file_id = item['file_id']

        if parent_file_name != 'root' and parent_file_id == 'root':
            parent_file_id = self.create_folder(parent_file_name)['file_id']

        if len(dirs) == 1:
            return parent_file_id

        for index, parent_file_name in enumerate(dirs[1:]):
            files = self.get_list(parent_file_id)['items']
            flag = True
            for item in files:
                if item['name'] == parent_file_name:
                    parent_file_id = item['file_id']
                    flag = False
            if flag:
                parent_file_id = self.create_folder(parent_file_name, parent_file_id)['file_id']
        return parent_file_id

    @staticmethod
    def _upload(path, upload_uri):
        with open(path, 'rb') as f:
            total_size = os.fstat(f.fileno()).st_size
            f = tqdm.wrapattr(f, "read", desc='Uploading...', miniters=1, total=total_size, ascii=True)
            with f as f_iter:
                res = requests.put(
                    upload_uri,
                    data=ChunksIter(f_iter, total_size=total_size)
                )
                res.raise_for_status()

    def _create(self, data):
        res = requests.post(self.base_api + 'file/create', headers=self.headers, json=data).json()
        if res.get('code') == 'AccessTokenInvalid':
            if self.do_refresh_token():
                print('Token Refresh Success!')
                return self._create(data)
            else:
                print('Token Refresh Failed!')
                exit(-1)
        return res

    def create_folder(self, name, parent_file_id="root"):
        """
        创建文件夹
        :param name: 文件夹名称
        :param parent_file_id: 父文件夹的ID, 默认为root
        :return:
        """
        data = {
            "drive_id": self.drive_id,
            "parent_file_id": parent_file_id,
            "name": name,
            "check_name_mode": "refuse",
            "type": "folder"
        }
        return self._create(data)

    def _create_file(self, parent_file_id, content_hash, name, size):
        data = {
            "auto_rename": True,
            "content_hash": content_hash,
            "content_hash_name": 'sha1',
            "drive_id": self.drive_id,
            "hidden": False,
            "name": name,
            "parent_file_id": parent_file_id,
            "type": "file",
            "size": size,
        }
        return self._create(data)

    def on_complete(self, file_id, upload_id):
        data = {
            "drive_id": self.drive_id,
            "file_id": file_id,
            "upload_id": upload_id,
        }
        res = requests.post(self.base_api + 'file/complete', headers=self.headers, json=data).json()
        if res.get('code') == 'AccessTokenInvalid':
            if self.do_refresh_token():
                print('Token Refresh Success!')
                return self.on_complete(file_id, upload_id)
            else:
                print('Token Refresh Failed!')
                exit(-1)
        return res

    @staticmethod
    def get_sha1_hash(filepath):
        with open(filepath, 'rb') as f:
            sha1 = hashlib.sha1()
            while True:
                chunk = f.readline()
                if not chunk:
                    break
                sha1.update(chunk)
            return sha1.hexdigest()

    def get_file_info(self, filepath):
        name = os.path.basename(filepath)
        content_hash = self.get_sha1_hash(filepath)
        size = os.path.getsize(filepath)
        return {
            "content_hash": content_hash,
            "name": name,
            "size": size,
        }

    def _upload_file(self, filepath, parent_file_id='root'):
        file_info = self.get_file_info(filepath)
        create_res = self._create_file(parent_file_id, **file_info)
        if create_res.get('rapid_upload'):
            print(f'Rapid Upload({filepath}) Success!')
            return True
        print(create_res)
        upload_uri = create_res['part_info_list'][0]['upload_url']
        file_id = create_res['file_id']
        upload_id = create_res['upload_id']
        self._upload(filepath, upload_uri)
        return self.on_complete(file_id, upload_id)

    def upload_file(self, filepath, parent: Union[None, str] = None):
        parent_file_id = 'root'
        if parent is None:
            return self._upload_file(filepath, parent_file_id)
        parent_file_id = self._get_parent_file_id(parent)
        return self._upload_file(filepath, parent_file_id)

    def get_all_file(self, path) -> List:
        result = []
        try:
            get_dir = os.listdir(path)
        except NotADirectoryError:
            return [path]
        for i in get_dir:
            sub_dir = os.path.join(path, i)
            if os.path.isdir(sub_dir):
                result.extend(self.get_all_file(sub_dir))
            else:
                result.append(sub_dir)
        return result

    def upload_folders(self, folder_path, parent: Union[None, str] = None):
        files = self.get_all_file(folder_path)
        for file in files:
            full_paths = file.split('/')[1:-1]
            if parent is None:
                self.upload_file(file, '/'.join(full_paths))
            else:
                self.upload_file(file, parent + '/' + '/'.join(full_paths))


if __name__ == '__main__':
    argv = sys.argv[1:]
    if len(argv) < 1:
        print('Must add a file or folder!')
    api = AliyunDriveApi()
    if len(argv) == 1:
        api.upload_folders(argv[0])
    else:
        api.upload_folders(argv[0], argv[1])
