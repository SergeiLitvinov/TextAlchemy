param([string]$InputPath,[ValidateSet('comments','protection')][string]$Kind,[string]$ExpectedComment='Own comment content',[string]$EditedPath)
$ErrorActionPreference='Stop'
$wordAcceptance=$null
$wordDocument=$null
try {
 $wordAcceptance=New-Object -ComObject Word.Application
 $wordAcceptance.Visible=$false
 $wordAcceptance.DisplayAlerts=0
 $wordAcceptance.AutomationSecurity=3
 $wordDocument=$wordAcceptance.Documents.Open([IO.Path]::GetFullPath($InputPath),$false,$false)
 $checks=@{}
 if ($Kind -eq 'comments') {
  $comment=$wordDocument.Comments.Item(1)
  $checks=@{count=($wordDocument.Comments.Count -eq 1);text=($comment.Range.Text -eq $ExpectedComment);author=($comment.Author -eq 'QA Author');initials=($comment.Initial -eq 'QA');scope=($comment.Scope.Text -eq 'Own commented paragraph.')}
 } else {
  $checks=@{protection=($wordDocument.ProtectionType -eq 3);text=($wordDocument.Content.Text.Trim() -eq 'Own protected paragraph.')}
 }
 if (@($checks.Values | Where-Object {$_ -ne $true}).Count) { throw 'Native Word property differs' }
 $editReopened=$null
 if ($Kind -eq 'comments' -and $EditedPath) {
  $wordDocument.Comments.Item(1).Range.Text='Own native comment edit'
  $wordDocument.SaveAs2([IO.Path]::GetFullPath($EditedPath),16)
  $wordDocument.Close(0)
  $wordDocument=$wordAcceptance.Documents.Open([IO.Path]::GetFullPath($EditedPath),$false,$true)
  $editReopened=($wordDocument.Comments.Item(1).Range.Text -eq 'Own native comment edit')
  if (-not $editReopened) { throw 'Comment edit did not reopen' }
 }
 @{program=@{name=$wordAcceptance.Name;version=$wordAcceptance.Version;build=$wordAcceptance.Build};checks=$checks;native_edit_reopened=$editReopened;visual_score=$null} | ConvertTo-Json -Depth 5 -Compress
} finally {
 if ($null -ne $wordDocument) { $wordDocument.Close(0) }
 if ($null -ne $wordAcceptance) { $wordAcceptance.Quit();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordAcceptance) }
}
