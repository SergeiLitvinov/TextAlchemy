function Str(el)
  local text = el.text
  text = text:gsub("&", "\\&")
  text = text:gsub("%$", "\\$")
  text = text:gsub("#", "\\#")
  text = text:gsub("_", "\\_")
  text = text:gsub("%^", "\\textasciicircum{}")
  text = text:gsub("%~", "\\textasciitilde{}")
  text = text:gsub("%{", "\\{")
  text = text:gsub("%}", "\\}")
  text = text:gsub("%]", "\\]")
  text = text:gsub("%[", "\\[")
  el.text = text
  return el
end
