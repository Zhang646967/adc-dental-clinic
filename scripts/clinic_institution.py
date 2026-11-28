"""Collect an institution's first configuration without command-line passwords."""
import argparse
import getpass
import json
import os
from pathlib import Path


FIELDS = [('clinic_code', '门店业务编号'), ('name', '门店名称'), ('postal_address', '详细地址'),
          ('supervisor_name', '负责人姓名'), ('phone', '联系电话'), ('email', '机构邮箱'),
          ('area_sqm', '营业面积（平方米）')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    path = parser.parse_args().destination
    if path.parent.stat().st_mode & 0o077:
        raise SystemExit('请选择仅所有者可访问的目录。')
    clinic = {key: input(label + '　').strip() for key, label in FIELDS}
    username = input('技术管理员用户名　').strip()
    password = getpass.getpass('新密码（至少 16 个字符）　')
    if not all(clinic.values()) or not username or len(password) < 16 or password != getpass.getpass('确认新密码　'):
        raise SystemExit('请核对机构资料和密码。')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'clinic': clinic, 'administrator': {'username': username, 'password': password}},
                  output, ensure_ascii=False)
        output.write('\n')


if __name__ == '__main__':
    main()
