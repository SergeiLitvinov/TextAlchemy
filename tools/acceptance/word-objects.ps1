# Own native QA only; no user documents or arbitrary OLE classes.
# https://learn.microsoft.com/en-us/office/vba/api/word.oleformat.object
param(
 [Parameter(Mandatory=$true)][string]$InputPath,
 [Parameter(Mandatory=$true)][ValidateSet('smartart','ole')][string]$Kind,
 [string]$EditedPath
)
$ErrorActionPreference='Stop'
$sourcePath=[IO.Path]::GetFullPath($InputPath)
if ($EditedPath -and [IO.Path]::GetFullPath($EditedPath) -eq $sourcePath) { throw 'Edit must use a separate output' }
$originalHash=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
$wordAcceptance=$null
$wordDocument=$null
$embeddedWorkbook=$null
$embeddedExcel=$null
function Observe-Object($document) {
 if ($document.InlineShapes.Count -ne 1) { throw 'Expected one own inline object' }
 $shape=$document.InlineShapes.Item(1)
 $data=@{width=[double]$shape.Width;height=[double]$shape.Height}
 if ($Kind -eq 'smartart') {
  if (-not $shape.HasSmartArt) { throw 'Missing SmartArt' }
  $data.layout=$shape.SmartArt.Layout.Id
  $data.nodes=@(for ($index=1;$index -le $shape.SmartArt.AllNodes.Count;$index++) {
   $shape.SmartArt.AllNodes.Item($index).TextFrame2.TextRange.Text
  })
 } else {
  $data.prog_id=$shape.OLEFormat.ProgID
  if ($data.prog_id -ne 'Excel.Sheet.12') { throw 'Unexpected OLE class' }
  $shape.OLEFormat.Activate()
  $script:embeddedWorkbook=$shape.OLEFormat.Object
  if ($null -eq $script:embeddedWorkbook) { throw 'Embedded workbook automation unavailable' }
  $script:embeddedExcel=$script:embeddedWorkbook.Application
  $script:embeddedExcel.Visible=$false
  $data.a1=$script:embeddedWorkbook.Worksheets.Item(1).Cells.Item(1,1).Value2
  $data.a2=$script:embeddedWorkbook.Worksheets.Item(1).Cells.Item(2,1).Value2
 }
 return $data
}
try {
 if ($Kind -eq 'ole') {
  # A just-closed own fixture server may still be exiting. Never terminate it.
  foreach ($process in @(Get-Process EXCEL -ErrorAction SilentlyContinue)) { [void]$process.WaitForExit(5000) }
  if (Get-Process EXCEL -ErrorAction SilentlyContinue) { throw 'Existing Excel process: do not share a user instance' }
 }
 $wordAcceptance=New-Object -ComObject Word.Application
 $wordAcceptance.Visible=$false
 $wordAcceptance.DisplayAlerts=0
 $wordAcceptance.AutomationSecurity=3
 $wordDocument=$wordAcceptance.Documents.Open($sourcePath,$false,$false)
 $before=Observe-Object $wordDocument
 if ($EditedPath) {
  if ($Kind -eq 'smartart') {
   $wordDocument.InlineShapes.Item(1).SmartArt.AllNodes.Item(1).TextFrame2.TextRange.Text='Own native node edit'
  } else {
   $embeddedWorkbook.Worksheets.Item(1).Cells.Item(1,1).Value2='Own native cell edit'
  }
  $wordDocument.SaveAs2([IO.Path]::GetFullPath($EditedPath),16)
 }
 $wordDocument.Close(0)
 $wordDocument=$null
 if ($EditedPath) {
  $wordDocument=$wordAcceptance.Documents.Open([IO.Path]::GetFullPath($EditedPath),$false,$true)
  $after=Observe-Object $wordDocument
  $wordDocument.Close(0)
  $wordDocument=$null
 } else { $after=$null }
 if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne $originalHash) { throw 'Original changed' }
 @{kind=$Kind;opened=$true;before=$before;after=$after;source_unchanged=$true;program=@{name=$wordAcceptance.Name;version=$wordAcceptance.Version;build=$wordAcceptance.Build};visual_score=$null} | ConvertTo-Json -Depth 6 -Compress
} finally {
 if ($null -ne $wordDocument) { $wordDocument.Close(0) }
 if ($null -ne $embeddedExcel) {
  $closingExcel=@(Get-Process EXCEL -ErrorAction SilentlyContinue)
  if ($null -ne $embeddedWorkbook) {
   [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($embeddedWorkbook)
   $embeddedWorkbook=$null
  }
  $embeddedExcel.Quit()
  [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($embeddedExcel)
  foreach ($process in $closingExcel) { [void]$process.WaitForExit(5000) }
 }
 if ($null -ne $wordAcceptance) {
  $wordAcceptance.Quit()
  [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordAcceptance)
 }
}
