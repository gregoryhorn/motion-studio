"""Read one installed public manual as data; never invoke/probe the actual tool."""
import gzip
import json
from pathlib import Path
import re


def main():
    source = Path('/usr/share/man/man1/sox.1.gz')
    text = gzip.decompress(source.read_bytes()).decode()
    header = next(line for line in text.splitlines() if line.startswith('.TH '))
    match = re.search(r'(?ms)^\.SH NAME\n(.{1,1000}?)^\.SH ', text)
    print(json.dumps(dict(source='/usr/share/man/man1/sox.1.gz', header=header,
                          excerpt=match.group(1) if match else None), indent=2))


if __name__ == '__main__': main()
