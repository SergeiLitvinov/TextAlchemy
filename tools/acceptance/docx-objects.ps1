param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][ValidateSet('smartart','ole')][string]$Kind
)
# Own native fixtures only. No user files, links or macros are imported.
# https://learn.microsoft.com/en-us/office/vba/api/word.inlineshapes.addsmartart
# https://learn.microsoft.com/en-us/office/vba/api/word.inlineshapes.addoleobject
$ErrorActionPreference='Stop'
$fixtureRoot=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
$excelAcceptance=$null
$workbookAcceptance=$null
$wordAcceptance=$null
$wordDocument=$null
try {
    if ($Kind -eq 'ole') {
        $excelAcceptance=New-Object -ComObject Excel.Application
        $excelAcceptance.Visible=$false
        $excelAcceptance.DisplayAlerts=$false
        $excelAcceptance.AutomationSecurity=3
        $workbookAcceptance=$excelAcceptance.Workbooks.Add()
        $workbookAcceptance.Worksheets.Item(1).Cells.Item(1,1).Value2='Own embedded cell'
        $workbookAcceptance.Worksheets.Item(1).Cells.Item(2,1).Value2=7
        $workbookAcceptance.SaveAs((Join-Path $fixtureRoot 'own-embedded.xlsx'),51)
        $workbookAcceptance.Close($false)
        $workbookAcceptance=$null
        $excelAcceptance.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excelAcceptance)
        $excelAcceptance=$null
    }
    $wordAcceptance=New-Object -ComObject Word.Application
    $wordAcceptance.Visible=$false
    $wordAcceptance.DisplayAlerts=0
    $wordAcceptance.AutomationSecurity=3
    $wordDocument=$wordAcceptance.Documents.Add()
    $wordDocument.Content.Text="Own $Kind acceptance`r`r"
    $fixtureRange=$wordDocument.Paragraphs.Item(2).Range
    $fixtureRange.Collapse(1)
    if ($Kind -eq 'smartart') {
        $layout=$wordAcceptance.SmartArtLayouts.Item(1)
        $shape=$wordDocument.InlineShapes.AddSmartArt($layout,$fixtureRange)
        while ($shape.SmartArt.AllNodes.Count -lt 3) { $null=$shape.SmartArt.AllNodes.Add() }
        for ($index=1; $index -le $shape.SmartArt.AllNodes.Count; $index++) {
            $shape.SmartArt.AllNodes.Item($index).TextFrame2.TextRange.Text="Own node $index"
        }
    } else {
        $missing=[Type]::Missing
        $shape=$wordDocument.InlineShapes.AddOLEObject(
            $missing,(Join-Path $fixtureRoot 'own-embedded.xlsx'),$false,$false,
            $missing,$missing,$missing,$fixtureRange)
    }
    $fixturePath=Join-Path $fixtureRoot "own-$Kind.docx"
    $wordDocument.SaveAs2($fixturePath,16)
    $program=@{name=$wordAcceptance.Name;version=$wordAcceptance.Version;build=$wordAcceptance.Build}
    $wordDocument.Close(0)
    $wordDocument=$null
    $wordDocument=$wordAcceptance.Documents.Open($fixturePath,$false,$true)
    if ($wordDocument.InlineShapes.Count -ne 1) { throw 'Expected own inline object' }
    $nativeShape=$wordDocument.InlineShapes.Item(1)
    if ($Kind -eq 'smartart') {
        if (-not $nativeShape.HasSmartArt -or $nativeShape.SmartArt.AllNodes.Count -lt 3) {
            throw 'Own SmartArt did not reopen'
        }
    } elseif ($nativeShape.OLEFormat.ProgID -ne 'Excel.Sheet.12') {
        throw 'Own embedded workbook did not reopen'
    }
    $wordDocument.Close(0)
    $wordDocument=$null
    @{
        kind=$Kind
        file=$fixturePath
        source_sha256=(Get-FileHash -LiteralPath $fixturePath -Algorithm SHA256).Hash.ToLowerInvariant()
        program=$program
        source_reopened=$true
    } | ConvertTo-Json -Depth 5 -Compress
} finally {
    if ($null -ne $workbookAcceptance) { $workbookAcceptance.Close($false) }
    if ($null -ne $excelAcceptance) {
        $excelAcceptance.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excelAcceptance)
    }
    if ($null -ne $wordDocument) { $wordDocument.Close(0) }
    if ($null -ne $wordAcceptance) {
        $wordAcceptance.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordAcceptance)
    }
}
