param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [string]$OutputPath,
    [switch]$InspectOnly
)
$ErrorActionPreference='Stop'
$acceptanceWord=$null
$acceptanceDocument=$null
$inputAbsolute=[IO.Path]::GetFullPath($InputPath)
$outputAbsolute=$null
if (-not $InspectOnly) { $outputAbsolute=[IO.Path]::GetFullPath($OutputPath) }
if (-not $InspectOnly -and ($inputAbsolute -eq $outputAbsolute -or (Test-Path -LiteralPath $outputAbsolute))) {
    throw 'Use a new separate output file for the acceptance edit'
}
function WordInventory($document) {
    $levels=@{}
    $tableGeometry=@()
    foreach ($table in $document.Tables) {
        try {
            $widths=@()
            foreach ($cell in $table.Rows.Item(1).Cells) { $widths += [double]$cell.Width }
            $tableGeometry += @{scope='first-row-native-cell-widths';available=$true;widths_points=$widths}
        } catch {
            # Merged/irregular rows may not expose a uniform native row. Do not infer widths.
            $tableGeometry += @{scope='first-row-native-cell-widths';available=$false;widths_points=$null;
                reason='native-first-row-widths-unavailable'}
        }
    }
    foreach ($paragraph in $document.Paragraphs) {
        $level=[int]$paragraph.OutlineLevel
        if ($level -lt 10) {
            $key=[string]$level
            if (-not $levels.ContainsKey($key)) { $levels[$key]=0 }
            $levels[$key]++
        }
    }
    $bytes=[Text.Encoding]::UTF8.GetBytes($document.Content.Text)
    $normalized=[regex]::Replace($document.Content.Text.Replace([string][char]7,' '),'\s+',' ').Trim()
    $sha=[Security.Cryptography.SHA256]::Create()
    try {
        $textHash=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
        $normalizedHash=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)))).Replace('-','').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    return @{
        paragraphs=[int]$document.Paragraphs.Count
        tables=[int]$document.Tables.Count
        table_geometry=$tableGeometry
        inline_images=[int]$document.InlineShapes.Count
        floating_shapes=[int]$document.Shapes.Count
        fields=[int]$document.Fields.Count
        pages=[int]$document.ComputeStatistics(2)
        heading_levels=$levels
        text_sha256=$textHash
        normalized_text_sha256=$normalizedHash
        whitespace_tokens=[regex]::Matches($normalized,'\S+').Count
    }
}
try {
    $acceptanceWord=New-Object -ComObject Word.Application
    $acceptanceWord.Visible=$false
    $acceptanceWord.DisplayAlerts=0
    $acceptanceWord.AutomationSecurity=3
    $acceptanceDocument=$acceptanceWord.Documents.Open($inputAbsolute,$false,$true)
    $before=WordInventory $acceptanceDocument
    if ($InspectOnly) {
        @{
            schema='user-corpus-word-inspection-v1'
            driver='word-com'
            program=@{name=$acceptanceWord.Name;version=$acceptanceWord.Version;build=$acceptanceWord.Build}
            checked_at=[DateTimeOffset]::UtcNow.ToString('o')
            artifact_sha256=(Get-FileHash -LiteralPath $inputAbsolute -Algorithm SHA256).Hash.ToLowerInvariant()
            inventory=$before
            full_semantic_acceptance=$null
        } | ConvertTo-Json -Depth 8 -Compress
        return
    }
    # Save a separate editable copy; never edit the supplied input.
    $acceptanceDocument.SaveAs2($outputAbsolute,16)
    $acceptanceDocument.Close(0)
    $acceptanceDocument=$acceptanceWord.Documents.Open($outputAbsolute,$false,$false)
    $marker='[TextAlchemy QA] '
    $priorMarkerCount=[regex]::Matches($acceptanceDocument.Content.Text,[regex]::Escape($marker)).Count
    $paragraphEdited=$false
    foreach ($paragraph in $acceptanceDocument.Paragraphs) {
        if ($paragraph.Range.Text.Trim().Length -gt 0) {
            $range=$acceptanceDocument.Range($paragraph.Range.Start,$paragraph.Range.Start)
            $range.InsertAfter($marker)
            $paragraphEdited=$true
            break
        }
    }
    if (-not $paragraphEdited) { throw 'No editable paragraph found' }
    $tableEdited=$null
    $priorCellMarkerCount=0
    if ($acceptanceDocument.Tables.Count -gt 0) {
        $cell=$acceptanceDocument.Tables.Item(1).Cell(1,1)
        $priorCellMarkerCount=[regex]::Matches($cell.Range.Text,[regex]::Escape('[Cell QA] ')).Count
        $range=$acceptanceDocument.Range($cell.Range.Start,$cell.Range.Start)
        $range.InsertAfter('[Cell QA] ')
        $tableEdited=$true
    }
    $acceptanceDocument.Save()
    $acceptanceDocument.Close(0)
    $acceptanceDocument=$acceptanceWord.Documents.Open($outputAbsolute,$false,$true)
    $after=WordInventory $acceptanceDocument
    $found=([regex]::Matches($acceptanceDocument.Content.Text,[regex]::Escape($marker)).Count -eq ($priorMarkerCount+1))
    if ($tableEdited -eq $true) {
        $cellMarkerCount=[regex]::Matches($acceptanceDocument.Tables.Item(1).Cell(1,1).Range.Text,[regex]::Escape('[Cell QA] ')).Count
        $tableEdited=($cellMarkerCount -eq ($priorCellMarkerCount+1))
    }
    @{
        schema='user-corpus-word-check-v1'
        driver='word-com'
        program=@{name=$acceptanceWord.Name;version=$acceptanceWord.Version;build=$acceptanceWord.Build}
        checked_at=[DateTimeOffset]::UtcNow.ToString('o')
        artifact_sha256=(Get-FileHash -LiteralPath $inputAbsolute -Algorithm SHA256).Hash.ToLowerInvariant()
        edited_sha256=(Get-FileHash -LiteralPath $outputAbsolute -Algorithm SHA256).Hash.ToLowerInvariant()
        before=$before
        after=$after
        checks=@{text_edit=[bool]$found;table_cell_edit=$tableEdited;save_reopen=$true}
        visual_score=$null
        full_semantic_acceptance=$null
    } | ConvertTo-Json -Depth 8 -Compress
} finally {
    if ($null -ne $acceptanceDocument) { $acceptanceDocument.Close(0) }
    if ($null -ne $acceptanceWord) {
        $acceptanceWord.Quit(0)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($acceptanceWord)
    }
}
