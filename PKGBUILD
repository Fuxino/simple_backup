# PKGBUILD

# Maintainer: Daniele Fucini <dfucini@gmail.com>

pkgname=simple_backup
pkgver=3.1.2.r1.ga4c4b88
pkgrel=1
pkgdesc='Simple backup script that uses rsync to copy files'
arch=('any')
url="https://github.com/Fuxino/simple_backup.git"
license=('GPL3')
makedepends=('git'
             'python-setuptools')
depends=('python'
         'rsync'
         'python-dotenv'
         'python-dbus'
         'python-systemd')
install=${pkgname}.install
source=(git+https://github.com/Fuxino/${pkgname}.git)
sha256sums=('SKIP')

pkgver() 
{  
   cd ${pkgname}
   git describe --long --tags | sed 's/\([^-]*-g\)/r\1/;s/-/./g'
}

build()
{
   cd ${srcdir}/${pkgname}
   python3 setup.py build
}

package()
{
   cd ${srcdir}/${pkgname}
   python3 setup.py install --root=${pkgdir} --optimize=1 --skip-build
}
