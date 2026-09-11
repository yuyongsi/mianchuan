import re

p = r'C:\ProgramData\Kaspersky Lab\AVP21.26\Report\report.rpt'
data = open(p, 'rb').read()
print('report.rpt 大小:', len(data))

kw = ['python', 'app.py', '.lnk', '.vbs', 'shui', '蓄水',
      'quarant', 'detect', 'threat', 'trojan', 'malware', 'danger',
      'not-a-virus', 'hacktool', 'object', '1d0', 'susp']

def show(label, s):
    if s and len(s) > 3:
        print(f'  {label}: {s[:220]}')

print('--- ASCII 含关键词的字符串 ---')
for m in re.finditer(rb'[\x20-\x7e]{4,}', data):
    s = m.group().decode('ascii', 'ignore')
    ls = s.lower()
    if any(k in ls for k in kw):
        show('ascii', s)

print('--- UTF-16LE 含关键词的字符串 ---')
u16 = data.decode('utf-16le', 'ignore')
for m in re.finditer(r'[\x20-\x7e]{4,}', u16):
    s = m.group()
    ls = s.lower()
    if any(k in ls for k in kw):
        show('utf16', s)

print('--- 文件末尾 2000 字节(可能是最近记录) ---')
tail = data[-2000:]
for m in re.finditer(rb'[\x20-\x7e]{3,}', tail):
    print('  ', m.group().decode('ascii', 'ignore')[:120])
