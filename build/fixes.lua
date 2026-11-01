-- Pandoc Lua filter for draft_final.md.
--
-- Two fixes the default writer does not give us:
--
-- 1. Pipe tables in this document declare no column widths, so pandoc emits
--    natural-width columns and long cells run past the margin. We derive the
--    widths from each table's actual content.
-- 2. Appendix sources are 117-character URLs written as code spans. \texttt
--    cannot break them; \url (with xurl loaded) breaks at any character.

local function plainlen(x)
  if x == nil then return 0 end
  if type(x) == "string" then return #x end
  if x.t == "Code" then return #x.text end
  if x.t == "Str" or x.t == "Math" then return #x.text end
  if x.t == "Space" or x.t == "SoftBreak" then return 1 end
  if x.content then
    local n = 0
    for _, c in ipairs(x.content) do n = n + plainlen(c) end
    return n
  end
  return 0
end

local function rowlens(row)
  local out = {}
  for i, cell in ipairs(row.cells) do
    local n = 0
    for _, blk in ipairs(cell.contents) do
      for _, inl in ipairs(blk.content or {}) do n = n + plainlen(inl) end
    end
    out[i] = n
  end
  return out
end

-- Flatten one cell to text so we can find its longest unbreakable token.
-- A column narrower than its longest word produces an overfull hbox no matter
-- how the rest of the cell wraps.
local function celltext(cell)
  local parts = {}
  for _, blk in ipairs(cell.contents) do
    for _, inl in ipairs(blk.content or {}) do
      if inl.t == "Str" or inl.t == "Code" or inl.t == "Math" then
        parts[#parts + 1] = inl.text
      elseif inl.t == "Space" or inl.t == "SoftBreak" or inl.t == "LineBreak" then
        parts[#parts + 1] = " "
      elseif inl.t == "RawInline" then
        parts[#parts + 1] = "x"
      else
        parts[#parts + 1] = string.rep("x", plainlen(inl))
      end
    end
    parts[#parts + 1] = " "
  end
  return table.concat(parts)
end

local function longestword(txt)
  local best = 1
  for w in txt:gmatch("[^%s]+") do
    if #w > best then best = #w end
  end
  return best
end

function Table(tbl)
  local ncols = #tbl.colspecs
  local maxlen, maxword = {}, {}
  for i = 1, ncols do
    maxlen[i] = 1
    maxword[i] = 1
  end

  local function absorb(row)
    local ls = rowlens(row)
    for i, cell in ipairs(row.cells) do
      if (ls[i] or 0) > maxlen[i] then maxlen[i] = ls[i] end
      local lw = longestword(celltext(cell))
      if lw > maxword[i] then maxword[i] = lw end
    end
  end

  if tbl.head and tbl.head.rows then
    for _, r in ipairs(tbl.head.rows) do absorb(r) end
  end
  for _, body in ipairs(tbl.bodies) do
    for _, r in ipairs(body.body) do absorb(r) end
  end

  -- Rough characters per line at this size and measure (A4, 2.3cm margins,
  -- 10pt). Only used to translate "longest word in characters" into a column
  -- fraction, so precision is not important.
  local LINE_CHARS = 88

  -- sqrt weighting compresses outliers: a 117-char URL earns more room than a
  -- 4-char label, without swallowing the page.
  local w, total = {}, 0
  for i = 1, ncols do
    w[i] = math.sqrt(maxlen[i])
    total = total + w[i]
  end

  local frac, acc = {}, 0
  for i = 1, ncols do
    frac[i] = math.min(math.max(w[i] / total, 0.10), 0.62)
    acc = acc + frac[i]
  end
  for i = 1, ncols do frac[i] = frac[i] / acc end

  -- Second pass: widen any column too narrow for its longest word. Bold text
  -- runs ~8% wider than regular, hence the 1.12 factor.
  for _ = 1, 6 do
    local changed = false
    for i = 1, ncols do
      local required = (maxword[i] * 1.12) / LINE_CHARS
      if frac[i] < required and required < 0.80 then
        frac[i] = required
        changed = true
      end
    end
    local sum = 0
    for i = 1, ncols do sum = sum + frac[i] end
    for i = 1, ncols do frac[i] = frac[i] / sum end
    if not changed then break end
  end

  local spec = {}
  for i = 1, ncols do
    spec[i] = { tbl.colspecs[i][1], frac[i] }
  end

  tbl.colspecs = spec
  return tbl
end

function Code(c)
  if c.text:match("^https?://") then
    return pandoc.RawInline("latex", "\\url{" .. c.text .. "}")
  end
end
