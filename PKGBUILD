#Arch Linux PKGBUILD
#
#Maintainer: Daniele Fucini <dfucini@gmail.com>
#

pkgname=simple-backup
pkgver=1.4.r0.g97d1a14
pkgrel=1
pkgdesc='Simple backup script that uses rsync to copy files'
arch=('any')
url="https://github.com/Fuxino"
license=('GPL3')
makedepends=('git')
depends=('python3'
         'rsync')
install=${pkgname}.install
source=(git+https://github.com/Fuxino/${pkgname}.git
        config)
sha256sums=('SKIP'
            '22ef4a0e9356daf3cabe93299c7a04b6b7283b14e6f2c07d939e24027eedf144')

pkgver() 
{  
   cd "$pkgname"
   git describe --long --tags | sed 's/\([^-]*-g\)/r\1/;s/-/./g'
}

package()
{
   install -Dm755 "${srcdir}/${pkgname}/${pkgname}" "${pkgdir}/usr/bin/${pkgname}"
   install -Dm644 "${srcdir}/config" "${pkgdir}/etc/${pkgname}/config"
}
