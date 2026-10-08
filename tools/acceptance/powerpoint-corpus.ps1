param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [string]$OutputPath,
    [string]$RenderDirectory,
    [switch]$InspectOnly
)
$ErrorActionPreference='Stop'
$presentation=$null
$powerpoint=$null
$ownsApplication= -not [bool](Get-Process POWERPNT -ErrorAction SilentlyContinue)
$oldSecurity=$null
$inputAbsolute=[IO.Path]::GetFullPath($InputPath)
$outputAbsolute=$null
if (-not $InspectOnly) {
    $outputAbsolute=[IO.Path]::GetFullPath($OutputPath)
    if ($inputAbsolute -eq $outputAbsolute -or (Test-Path -LiteralPath $outputAbsolute)) {
        throw 'Use a fresh separate output file'
    }
}
$renderAbsolute=$null
if ($RenderDirectory) {
    $renderAbsolute=[IO.Path]::GetFullPath($RenderDirectory)
    $renderRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../.textalchemy/acceptance'))
    if (-not $renderAbsolute.StartsWith($renderRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Native slide images must stay in the separate local acceptance directory'
    }
    if (Test-Path -LiteralPath $renderAbsolute) { throw 'Use a fresh native render directory' }
    [void](New-Item -ItemType Directory -Path $renderAbsolute)
}
function PresentationInventory($document) {
    $slides=@()
    foreach ($slide in $document.Slides) {
        $text=@()
        $boxes=@()
        $charts=0
        $tables=0
        foreach ($shape in $slide.Shapes) {
            if ($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1) { $text += $shape.TextFrame.TextRange.Text }
            if ($shape.HasChart -eq -1) { $charts++ }
            if ($shape.HasTable -eq -1) { $tables++ }
            $boxes += @{type=[int]$shape.Type;left=[double]$shape.Left;top=[double]$shape.Top;
                width=[double]$shape.Width;height=[double]$shape.Height;rotation=[double]$shape.Rotation}
        }
        $normalized=[regex]::Replace(($text -join ' '),'\s+',' ').Trim()
        $sha=[Security.Cryptography.SHA256]::Create()
        try { $hash=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)))).Replace('-','').ToLowerInvariant() }
        finally { $sha.Dispose() }
        $slides += @{shapes=[int]$slide.Shapes.Count;charts=$charts;tables=$tables;top_level_boxes=$boxes;
            normalized_text_sha256=$hash;whitespace_tokens=[regex]::Matches($normalized,'\S+').Count}
    }
    return @{slide_count=[int]$document.Slides.Count;slide_width=[double]$document.PageSetup.SlideWidth;
        slide_height=[double]$document.PageSetup.SlideHeight;slides=$slides}
}
try {
    $powerpoint=New-Object -ComObject PowerPoint.Application
    $oldSecurity=$powerpoint.AutomationSecurity
    $powerpoint.AutomationSecurity=3
    $presentation=$powerpoint.Presentations.Open($inputAbsolute,-1,0,0)
    $before=PresentationInventory $presentation
    $record=@{schema='user-corpus-powerpoint-check-v1';driver='powerpoint-com';
        program=@{name='Microsoft PowerPoint';version=[string]$powerpoint.Version;build=[string]$powerpoint.Build};
        checked_at=[DateTimeOffset]::UtcNow.ToString('o');
        artifact_sha256=(Get-FileHash -LiteralPath $inputAbsolute -Algorithm SHA256).Hash.ToLowerInvariant();
        visual_score=$null;full_semantic_acceptance=$null}
    if ($renderAbsolute) {
        $renderWidth=1280
        $renderHeight=[int][Math]::Round($renderWidth*$presentation.PageSetup.SlideHeight/$presentation.PageSetup.SlideWidth)
        $renderFiles=@()
        foreach ($slide in $presentation.Slides) {
            $renderName=('slide-{0:D3}.png' -f [int]$slide.SlideIndex)
            $renderPath=Join-Path $renderAbsolute $renderName
            $slide.Export($renderPath,'PNG',$renderWidth,$renderHeight)
            $renderFiles+=@{slide=[int]$slide.SlideIndex;file=$renderName;
                sha256=(Get-FileHash -LiteralPath $renderPath -Algorithm SHA256).Hash.ToLowerInvariant()}
        }
        $record.native_render=@{basis='PowerPoint-Slide.Export-PNG';scope='all-slides-before-QA-edit';
            width=$renderWidth;height=$renderHeight;files=$renderFiles}
    }
    if ($InspectOnly) {
        $record.inventory=$before
        $record | ConvertTo-Json -Depth 12 -Compress
        return
    }
    $presentation.SaveAs($outputAbsolute,24)
    $presentation.Close()
    $presentation=$null
    $presentation=$powerpoint.Presentations.Open($outputAbsolute,0,0,0)
    $marker='[TextAlchemy QA] '
    $editedSlide=0
    $editedShape=0
    $priorCount=0
    foreach ($slide in $presentation.Slides) {
        $nativeShapeIndex=0
        foreach ($shape in $slide.Shapes) {
            $nativeShapeIndex++
            if ($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1) {
                $range=$shape.TextFrame.TextRange
                $priorCount=[regex]::Matches($range.Text,[regex]::Escape($marker)).Count
                [void]$range.InsertAfter($marker)
                $editedSlide=[int]$slide.SlideIndex
                $editedShape=$nativeShapeIndex
                break
            }
        }
        if ($editedSlide -gt 0) { break }
    }
    if ($editedSlide -eq 0) { throw 'No top-level editable text shape found' }
    $chartEdited=$null
    $chartSlide=0
    $chartShape=0
    $expectedChartValue=$null
    foreach ($slide in $presentation.Slides) {
        $nativeShapeIndex=0
        foreach ($shape in $slide.Shapes) {
            $nativeShapeIndex++
            if ($shape.HasChart -eq -1 -and $shape.Chart.SeriesCollection().Count -gt 0) {
                $series=$shape.Chart.SeriesCollection(1)
                $values=@($series.Values)
                $expectedChartValue=[double]$values[0]+1
                $values[0]=$expectedChartValue
                $series.Values=$values
                $chartSlide=[int]$slide.SlideIndex
                $chartShape=$nativeShapeIndex
                break
            }
        }
        if ($chartSlide -gt 0) { break }
    }
    $presentation.Save()
    $presentation.Close()
    $presentation=$null
    $presentation=$powerpoint.Presentations.Open($outputAbsolute,-1,0,0)
    $range=$presentation.Slides.Item($editedSlide).Shapes.Item($editedShape).TextFrame.TextRange
    $record.before=$before
    $record.after=PresentationInventory $presentation
    $record.checks=@{text_edit=([regex]::Matches($range.Text,[regex]::Escape($marker)).Count -eq ($priorCount+1));save_reopen=$true}
    if ($chartSlide -gt 0) {
        $values=@($presentation.Slides.Item($chartSlide).Shapes.Item($chartShape).Chart.SeriesCollection(1).Values)
        $chartEdited=([double]$values[0] -eq $expectedChartValue)
    }
    $record.checks.chart_series_edit=$chartEdited
    $record.chart_series_observation=$null
    if ($chartSlide -gt 0) {
        $record.chart_series_observation=@{expected_first_value=$expectedChartValue;observed_first_value=[double]$values[0];
            scope='first-series-values-com';embedded_workbook_edit=$null}
    }
    $record.edited_sha256=(Get-FileHash -LiteralPath $outputAbsolute -Algorithm SHA256).Hash.ToLowerInvariant()
    $record | ConvertTo-Json -Depth 12 -Compress
} finally {
    if ($null -ne $presentation) { $presentation.Close() }
    if ($null -ne $powerpoint) {
        if ($null -ne $oldSecurity) { $powerpoint.AutomationSecurity=$oldSecurity }
        if ($ownsApplication -and $powerpoint.Presentations.Count -eq 0) { $powerpoint.Quit() }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($powerpoint)
    }
}
