import os
import re
import requests
import subprocess

filename = 'requirements.txt'
new_packages = []
# we skip these because models may act unpredictably between versions
# must be updated manually
packages_to_skip = []
pattern = r'(\S*)\s?==\s?(\S*)'

with open(filename, 'r') as file:
    for line in file:
        match = re.match(pattern, line)
        line = line.strip()
        if match:
            package, version = match.groups()
            response = requests.get(f'https://pypi.org/pypi/{package}/json')
            keys = response.json()['releases'].keys()
            releases = [key for key in keys if key.replace('.', '').isdigit()]
            latest = sorted(
                releases,
                key=lambda release: [
                    int(number) for number in release.split('.')
                ]).pop()
            if latest != version and package not in packages_to_skip:
                print(f'Upgrading {package} ({version} => {latest})')
                CI = os.environ.get('CI')
                python = 'python' if CI else 'python3'
                cmd = f'{python} -m pip install {package}=={latest}'
                code = subprocess.run(cmd, shell=True).returncode
                if code:
                    exit(code)
                version = latest

            new_packages.append({'package': package, 'version': version})
        elif line:
            new_packages.append({'package': line})

with open(filename, 'w') as file:
    for package in new_packages:
        prefix = package['package']
        suffix = (
            f"{' == ' + package['version'] if 'version' in package else ''}\n")
        file.write(f"{prefix}{suffix}")
