import argparse
import hashlib
import json
import os

import oss2
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from oss2.credentials import EnvironmentVariableCredentialsProvider


class OssClientBase:
    def auth(self):
        return oss2.ProviderAuth(EnvironmentVariableCredentialsProvider())

    def normalize_endpoint(self, endpoint):
        if 'oss' not in endpoint:
            endpoint = 'oss-' + endpoint
        if '.' not in endpoint:
            endpoint += '.aliyuncs.com'
        return endpoint

    def get_encrypt_key(self, key):
        if len(key) in (32, 64):
            try:
                return bytes.fromhex(key)
            except ValueError:
                pass
        return hashlib.sha256(key.encode('utf-8')).digest()

class Uploader(OssClientBase):
    def __init__(self, endpoint, bucket, prefix, files, encrypt_key):
        self.endpoint = self.normalize_endpoint(endpoint)
        self.bucket = bucket
        self.prefix = prefix
        self.files = files
        self.encrypt_key = self.get_encrypt_key(encrypt_key)

    def collect_files(self, files):
        ret = []
        for file in files:
            if not os.path.exists(file):
                raise ValueError(f'File {file} does not exist')
            if os.path.isdir(file):
                for root, _, filenames in os.walk(file):
                    for filename in filenames:
                        filepath = os.path.join(root, filename)
                        key = os.path.relpath(filepath, file)
                        ret.append((filepath, key))
            else:
                ret.append((file, os.path.basename(file)))
        return ret

    def upload(self):
        file_data = self.collect_files(self.files)
        bucket = oss2.Bucket(self.auth(), self.endpoint, self.bucket)
        choice = None

        for file, key in file_data:
            key = self.prefix + key
            if bucket.object_exists(key):
                while choice != 'a':
                    choice = input(f'File {key} already exists, select an action: [o]verwrite, [s]kip, [a]lways overwrite, [q]uit: ')
                    if choice in ('o', 's', 'a', 'q'):
                        break
                if choice == 's':
                    continue
                if choice == 'q':
                    return

            with open(file, 'rb') as f:
                data = f.read()
                print(f'Uploading {file} to {self.bucket}:{key} with {len(data)} bytes')
                bucket.put_object(key, self.encrypt(data))

    def encrypt(self, data):
        nonce = get_random_bytes(8)
        cipher = AES.new(self.encrypt_key, AES.MODE_CTR, nonce=nonce)
        enc_data = cipher.encrypt(data)
        return cipher.nonce + enc_data


class Downloader(OssClientBase):
    def __init__(self, endpoint, bucket, files, output_dir, encrypt_key):
        self.endpoint = self.normalize_endpoint(endpoint)
        self.bucket = bucket
        self.output_dir = output_dir
        self.files = files
        self.encrypt_key = self.get_encrypt_key(encrypt_key)

    def download(self):
        bucket = oss2.Bucket(self.auth(), self.endpoint, self.bucket)
        for file in self.files:
            for obj in oss2.ObjectIterator(bucket, prefix=file):
                data = bucket.get_object(obj.key)
                path = os.path.join(self.output_dir, obj.key)
                print(f'Downloading {obj.key} to {path}')
                if not os.path.exists(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'wb') as f:
                    f.write(self.decrypt(data.read()))

    def decrypt(self, data):
        nonce = data[:8]
        cipher = AES.new(self.encrypt_key, AES.MODE_CTR, nonce=nonce)
        return cipher.decrypt(data[8:])


class Lister(OssClientBase):
    def __init__(self, endpoint, bucket, prefix):
        self.endpoint = self.normalize_endpoint(endpoint)
        self.bucket = bucket
        self.prefix = prefix

    def list(self):
        bucket = oss2.Bucket(self.auth(), self.endpoint, self.bucket)
        for obj in oss2.ObjectIterator(bucket, prefix=self.prefix):
            print(obj.key)


def parse():
    config = {}
    if os.path.exists('config.json'):
        with open('config.json') as f:
            config = json.load(f)

    parser = argparse.ArgumentParser(description='SOSS: Secure Object Storage Service')
    subparsers = parser.add_subparsers(required=True, dest='command')

    upload_parser = subparsers.add_parser('upload')
    upload_parser.add_argument('files', nargs='+', help='file to upload')
    upload_parser.add_argument('--endpoint', '-e', help='endpoint to upload to', default=config.get('endpoint'))
    upload_parser.add_argument('--bucket', '-b', help='bucket to upload to', default=config.get('bucket'))
    upload_parser.add_argument('--prefix', help='prefix to add to the file name', default='')
    upload_parser.add_argument('--encrypt_key', '-k', help='encryption key', required=True)

    download_parser = subparsers.add_parser('download')
    download_parser.add_argument('files', nargs='+', help='file to download')
    download_parser.add_argument('--endpoint', '-e', help='endpoint to upload to', default=config.get('endpoint'))
    download_parser.add_argument('--bucket', '-b', help='bucket to download from', default=config.get('bucket'))
    download_parser.add_argument('--output_dir', help='output directory', default='./downloads')
    download_parser.add_argument('--encrypt_key', '-k', help='encryption key', required=True)

    list_parser = subparsers.add_parser('list')
    list_parser.add_argument('--endpoint', '-e', help='endpoint to upload to', default=config.get('endpoint'))
    list_parser.add_argument('--bucket', '-b', help='bucket to list', default=config.get('bucket'))
    list_parser.add_argument('--prefix', help='object prefix to list', default='')

    return parser.parse_args()


def main():
    options = parse()
    if options.command == 'upload':
        uploader = Uploader(options.endpoint, options.bucket, options.prefix, options.files, options.encrypt_key)
        uploader.upload()
    elif options.command == 'download':
        downloader = Downloader(options.endpoint, options.bucket, options.files, options.output_dir, options.encrypt_key)
        downloader.download()
    elif options.command == 'list':
        lister = Lister(options.endpoint, options.bucket, options.prefix)
        lister.list()
    else:
        assert False, 'Unknown command'


if __name__ == '__main__':
    main()
