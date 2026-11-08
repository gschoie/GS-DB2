# ecos-fx-rates 로 보낼 패치

이 폴더의 `.patch` 는 **별도 리포 `gschoie/ecos-fx-rates`** 에 적용할 변경이다(이 리포가 아니다).
클라우드 세션이 ecos-fx-rates 에 push 권한을 못 받았을 때 여기 떨궈 둔다.

적용(로컬 PC 또는 push 권한이 있는 세션):

```bash
cd ecos-fx-rates
git am /path/to/GS-DB2/peergroup/patches/0001-*.patch
git push origin main
```

적용 후 Actions '피어그룹 주가 엑셀' 을 한 번 돌리면 `output/peer_price_defense/`·`output/peer_price_construction/`
가 생기고 대시보드 `peer_price.html?u=defense|construction` 이 그림을 띄운다. 적용이 끝난 패치는 지운다.
