param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][string]$FindText,
    [Parameter(Mandatory=$true)][string]$Replacement
)
$ErrorActionPreference='Stop'
$wordAcceptance=$null
$wordDocument=$null
try {
    $wordAcceptance=New-Object -ComObject Word.Application
    $wordAcceptance.Visible=$false
    $wordAcceptance.DisplayAlerts=0
    $wordAcceptance.AutomationSecurity=3
    $wordDocument=$wordAcceptance.Documents.Open([IO.Path]::GetFullPath($InputPath),$false,$false)
    $wordRange=$wordDocument.Content
    $wordRange.Find.Text=$FindText
    if (-not $wordRange.Find.Execute()) { throw 'Expected editable paragraph not found' }
    $wordRange.Text=$Replacement
    $wordDocument.Tables.Item(1).Cell(2,2).Range.Text='42'
    $wordDocument.SaveAs2([IO.Path]::GetFullPath($OutputPath),16)
    $wordDocument.Close(0)
    $wordDocument=$null
    $wordDocument=$wordAcceptance.Documents.Open([IO.Path]::GetFullPath($OutputPath),$false,$true)
    $reopenedRange=$wordDocument.Content
    $reopenedRange.Find.Text=$Replacement
    $found=$reopenedRange.Find.Execute()
    $cellText=$wordDocument.Tables.Item(1).Cell(2,2).Range.Text.Replace([string][char]13,'').Replace([string][char]7,'')
    @{
        schema='target-program-check-v1'
        driver='word-com'
        program=@{name=$wordAcceptance.Name;version=$wordAcceptance.Version;build=$wordAcceptance.Build}
        checked_at=[DateTimeOffset]::UtcNow.ToString('o')
        artifact_sha256=(Get-FileHash -LiteralPath $InputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        edited_sha256=(Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        scope=@('paragraph_text','table_cell','heading_outline','inline_image','bold','save_reopen')
        checks=@{
            text_edit=[bool]$found
            table_cell_edit=($cellText -eq '42')
            save_reopen=$true
            heading_outline=($wordDocument.Paragraphs.Item(1).OutlineLevel -eq 2)
            inline_image=($wordDocument.InlineShapes.Count -eq 1)
            bold=($found -and $reopenedRange.Font.Bold -eq -1)
        }
        observations=@{heading_outline_level=[int]$wordDocument.Paragraphs.Item(1).OutlineLevel}
        visual_score=$null
    } | ConvertTo-Json -Depth 5 -Compress
} finally {
    if ($null -ne $wordDocument) { $wordDocument.Close(0) }
    if ($null -ne $wordAcceptance) {
        $wordAcceptance.Quit(0)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordAcceptance)
    }
}
