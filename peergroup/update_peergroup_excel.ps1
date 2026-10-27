# ============================================================
# 피어그룹 엑셀 업데이트 (update_peergroup_excel.ps1)
#
# GitHub Actions에서 받은 '글로벌_주가_변동률_모니터링_최종.xlsx'의
# 시트 내용을, 같은 폴더에 있는 차트(그림) 엑셀 파일의
# "같은 이름 시트"에 값+서식으로 붙여넣는다.
#
# 자동으로 처리하는 것들 (복붙 프로그램이 멈추는 흔한 원인):
#  1. 다운로드 파일의 인터넷 차단(Mark of the Web) 해제
#  2. "이 이름이 이미 있습니다" 등 엑셀 경고창 전부 억제
#  3. 대상 파일에 쌓인 깨진 이름(#REF!)과 중복된
#     정의된 이름(주가데이터, 주가데이터H) 정리
#  4. 예전 시트 복사로 생긴 원본 파일로의 외부 링크 끊기
#  5. 원본이 폴더에 없으면 다운로드 폴더에서 xlsx 또는
#     '피어그룹-주가-엑셀*.zip'을 찾아 자동으로 가져오기
#
# 사용법: 같은 폴더의 피어그룹_엑셀_업데이트.bat 을 더블클릭
# ============================================================

$ErrorActionPreference = 'Stop'

# ===== 설정 (필요하면 여기만 수정) =====
$SourceName = '글로벌_주가_변동률_모니터링_최종.xlsx'
$TargetName = ''    # 대상(차트) 파일명. 비워두면 폴더에서 자동 탐색
$SheetNames = @()   # 복사할 시트 목록. 비워두면 양쪽에 공통인 모든 시트
# =======================================

$Folder = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "작업 폴더: $Folder"

# ---------- 1) 원본 파일 찾기 ----------
$srcPath = Join-Path $Folder $SourceName
if (-not (Test-Path $srcPath)) {
    Write-Host "폴더에 원본이 없어 다운로드 폴더를 확인합니다..." -ForegroundColor Yellow
    $dl = Join-Path $env:USERPROFILE 'Downloads'
    $cand = Get-ChildItem $dl -Filter $SourceName -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($cand) {
        Copy-Item $cand.FullName $srcPath -Force
        Write-Host "다운로드 폴더에서 복사함: $($cand.FullName)"
    } else {
        $zip = Get-ChildItem $dl -Filter '피어그룹-주가-엑셀*.zip' -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($zip) {
            Expand-Archive $zip.FullName -DestinationPath $Folder -Force
            Write-Host "zip 압축 해제함: $($zip.FullName)"
        }
    }
}
if (-not (Test-Path $srcPath)) {
    throw "원본 파일을 찾지 못했습니다: $SourceName (이 폴더 또는 다운로드 폴더에 놓아주세요)"
}
Unblock-File $srcPath -ErrorAction SilentlyContinue

# ---------- 2) 대상(차트) 파일 찾기 ----------
if ($TargetName) {
    $tgtPath = Join-Path $Folder $TargetName
    if (-not (Test-Path $tgtPath)) { throw "대상 파일이 없습니다: $TargetName" }
} else {
    $cands = @(Get-ChildItem -Path (Join-Path $Folder '*') -Include '*.xlsx','*.xlsm' |
             Where-Object { $_.Name -ne $SourceName -and $_.Name -notlike '~$*' })
    if ($cands.Count -eq 0) { throw "대상 엑셀 파일이 폴더에 없습니다. 스크립트 상단 `$TargetName 에 파일명을 적어주세요." }
    if ($cands.Count -gt 1) {
        Write-Host "대상 후보가 여러 개입니다:" -ForegroundColor Yellow
        $cands | ForEach-Object { Write-Host "  - $($_.Name)" }
        throw "스크립트 상단 `$TargetName 에 대상 파일명을 정확히 적어주세요."
    }
    $tgtPath = $cands[0].FullName
}
Unblock-File $tgtPath -ErrorAction SilentlyContinue
Write-Host "원본: $srcPath"
Write-Host "대상: $tgtPath"

# ---------- 3) 엑셀 COM으로 시트 내용 복사 ----------
$excel = $null; $wbS = $null; $wbT = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false        # 이름 충돌 등 모든 경고창 억제
    $excel.AskToUpdateLinks = $false
    $excel.ScreenUpdating = $false

    $wbS = $excel.Workbooks.Open($srcPath, 0, $true)   # 원본은 읽기 전용
    $wbT = $excel.Workbooks.Open($tgtPath, 0, $false)

    if ($wbT.ReadOnly) {
        throw "대상 파일이 읽기 전용으로 열렸습니다. 다른 PC/엑셀에서 열려 있거나 OneDrive 동기화 중입니다. 닫고 다시 실행하세요."
    }

    # 3-1) 대상 파일의 깨진 이름·중복 이름 정리 (멈춤의 주범)
    $removed = 0
    foreach ($n in @($wbT.Names)) {
        $refersTo = ''
        try { $refersTo = $n.RefersTo } catch { }
        if ($refersTo -match '#REF!' -or $n.Name -match '주가데이터') {
            try { $n.Delete(); $removed++ } catch { }
        }
    }
    if ($removed -gt 0) { Write-Host "대상 파일에서 깨진/중복 이름 $removed 개 정리" }

    # 3-2) 복사할 시트 결정: 양쪽에 같은 이름으로 존재하는 시트
    $srcSheets = @($wbS.Worksheets | ForEach-Object { $_.Name })
    $tgtSheets = @($wbT.Worksheets | ForEach-Object { $_.Name })
    $list = if ($SheetNames.Count -gt 0) { $SheetNames } else { $srcSheets | Where-Object { $tgtSheets -contains $_ } }
    if (-not $list) {
        throw "복사할 공통 시트가 없습니다. 원본: [$($srcSheets -join ', ')] / 대상: [$($tgtSheets -join ', ')]"
    }
    $notInTarget = $srcSheets | Where-Object { $tgtSheets -notcontains $_ }
    if ($notInTarget) { Write-Host "대상에 없어 건너뜀: $($notInTarget -join ', ')" -ForegroundColor Yellow }

    # 3-3) 시트별로 값+서식 붙여넣기 (시트 자체를 삭제하지 않으므로
    #      대상 파일의 차트가 참조하는 범위가 깨지지 않는다)
    foreach ($name in $list) {
        Write-Host "  ▶ '$name' 복사 중..."
        $srcWs = $wbS.Worksheets.Item($name)
        $dstWs = $wbT.Worksheets.Item($name)
        $dstWs.Cells.Clear() | Out-Null
        $srcWs.Cells.Copy() | Out-Null
        $dstWs.Range('A1').PasteSpecial(-4122) | Out-Null   # 서식(병합 포함)
        $dstWs.Range('A1').PasteSpecial(8)     | Out-Null   # 열 너비
        $dstWs.Range('A1').PasteSpecial(12)    | Out-Null   # 값+숫자서식
        $excel.CutCopyMode = $false
    }

    # 3-4) 예전 시트 복사로 남아있는 원본 파일로의 외부 링크 제거
    $links = $wbT.LinkSources(1)   # 1 = xlLinkTypeExcelLinks
    if ($links) {
        foreach ($l in @($links)) {
            if ($l -match '글로벌_주가_변동률') {
                try { $wbT.BreakLink($l, 1); Write-Host "외부 링크 끊음: $l" } catch { }
            }
        }
    }

    $wbT.Save()
    Write-Host ""
    Write-Host "✅ 완료! '$([IO.Path]::GetFileName($tgtPath))' 에 시트 $($list.Count)개 업데이트: $($list -join ', ')" -ForegroundColor Green
}
finally {
    if ($wbS) { try { $wbS.Close($false) } catch { } }
    if ($wbT) { try { $wbT.Close($false) } catch { } }
    if ($excel) {
        try { $excel.Quit() } catch { }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
