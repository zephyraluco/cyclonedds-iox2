#!/bin/bash
set -e

script=$(readlink -f "$0")
route=$(dirname "$script")

tgt_version=$1
tgt_install_prefix=$2
pkg_name=cyclonedds-iox2

if [ "${tgt_version}" == "" ]; then
    tgt_version=$(git describe --tags 2>/dev/null || echo "0.0.0")
    if [ "${tgt_version}" == "0.0.0" ] && [ -e "${route}/../version" ]; then
        tgt_version=$(cat ${route}/../version)
        echo "No version number can be achieved from git, so we use value in '${pkg_name}/version' as the target version: ${tgt_version}"
    fi
fi
echo ${tgt_version} > ${route}/../version
echo "Version is ${tgt_version} and it has been written into 'proj_root/version'"

if [ "${tgt_install_prefix}" == "" ]; then
    tgt_install_prefix=/usr/local
fi
echo "deb install prefix is ${tgt_install_prefix}"

uname_arch=$(uname -m)
if [ x"${uname_arch}" == x"x86_64" ]; then
    arch=amd64
elif [ x"${uname_arch}" == x"aarch64" ]; then
    arch=arm64
else
    echo "not support arch ${uname_arch}" >&2
    exit 2
fi

### 1. make the working dir
if [ -e ${route}/../dist ]; then
    rm -rf ${route}/../dist
fi
mkdir -p ${route}/../dist/${pkg_name}
mkdir -p ${route}/../dist/${pkg_name}/DEBIAN
mkdir -p ${route}/../dist/${pkg_name}/${tgt_install_prefix}

## 2. copy targets to deb ready dir
cp -r ${route}/../install/* ${route}/../dist/${pkg_name}/${tgt_install_prefix}/

## 3. make various config files under DEBIAN dir
cd ${route}/../dist/${pkg_name}/DEBIAN
touch control
(cat << EOF
Package: ${pkg_name}
Version: ${tgt_version}
Section: utils
Priority: optional
Depends: 
Suggests:
Architecture: ${arch}
Maintainer: zeal
CopyRight: commercial
Provider: zeal
Description: cyclonedds with iceoryx2 binding package
EOF
) > control

touch postinst
(cat << EOF
#!/bin/bash
sudo ldconfig
EOF
) > postinst

touch postrm
(cat << EOF
#!/bin/bash
EOF
) > postrm

touch preinst
(cat << EOF
#!/bin/bash
EOF
) > preinst

touch prerm
(cat << EOF
#!/bin/bash
EOF
) >> prerm

chmod +x postinst postrm preinst prerm

## 4. start to make .deb package
cd ${route}/..
fakeroot dpkg -b dist/${pkg_name} dist/${pkg_name}_${tgt_version}_${arch}.deb || exit 40
rm -rf dist/${pkg_name}
echo "pack ${pkg_name} into deb finished."
exit 0
