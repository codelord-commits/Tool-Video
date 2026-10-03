// Sinh form tự động từ JSON Schema của Preset (pydantic) — không code tay từng ô.

function resolve(root, s) {
  while (s && s.$ref) s = root.$defs[s.$ref.split("/").pop()];
  return s;
}

function unwrapNullable(root, s) {
  if (s.anyOf) {
    const nonNull = s.anyOf.filter((x) => x.type !== "null");
    const nullable = nonNull.length < s.anyOf.length;
    if (nonNull.length === 1) return { s: resolve(root, nonNull[0]), nullable, raw: nonNull[0] };
    return { s: { anyOf: nonNull }, nullable, raw: s };
  }
  return { s: resolve(root, s), nullable: false, raw: s };
}

function enumOf(root, s) {
  if (s.enum) return s.enum;
  if (s.const !== undefined) return [s.const];
  if (s.anyOf) {
    const out = [];
    for (const x of s.anyOf) {
      const r = resolve(root, x);
      if (r.enum) out.push(...r.enum);
      else if (r.const !== undefined) out.push(r.const);
    }
    return out.length ? out : null;
  }
  return null;
}

export function defaultsFor(root, s) {
  s = resolve(root, s);
  const out = {};
  for (const [k, p] of Object.entries(s.properties || {})) {
    if (p.default !== undefined) out[k] = JSON.parse(JSON.stringify(p.default));
    else {
      const { s: inner, nullable } = unwrapNullable(root, p);
      if (inner.type === "object" && inner.properties && !nullable) out[k] = defaultsFor(root, inner);
      else if (nullable) out[k] = null;
    }
  }
  return out;
}

/**
 * Danh sách field phẳng cho 1 object trong preset.
 * @param root  JSON schema gốc
 * @param def   tên $defs (ví dụ "Region") hoặc schema
 * @param base  đường dẫn dữ liệu (ví dụ "timeline.0.region")
 * @param opts  { exclude: [...tên], only: [...tên] }
 */
export function buildFields(root, def, base, opts = {}, depth = 0, showIf = null) {
  const s = typeof def === "string" ? root.$defs[def] : resolve(root, def);
  const fields = [];
  for (const [name, prop] of Object.entries(s.properties || {})) {
    if (opts.exclude && depth === 0 && opts.exclude.includes(name)) continue;
    if (opts.only && depth === 0 && !opts.only.includes(name)) continue;
    const path = base ? `${base}.${name}` : name;
    const { s: inner, nullable } = unwrapNullable(root, prop);
    const label = prop.title || inner.title || name;
    const desc = prop.description || inner.description || "";
    const f = { key: path, path, name, label, desc, nullable, depth, showIf, default: prop.default };
    const en = enumOf(root, inner);
    if (en) {
      fields.push({ ...f, type: "enum", options: en });
    } else if (inner.type === "boolean") {
      fields.push({ ...f, type: "bool" });
    } else if (inner.type === "integer" || inner.type === "number") {
      const min = inner.minimum ?? inner.exclusiveMinimum, max = inner.maximum ?? inner.exclusiveMaximum;
      const step = inner.type === "integer" ? 1 : (max !== undefined && min !== undefined && max - min <= 4 ? 0.01 : 0.1);
      fields.push({ ...f, type: "number", int: inner.type === "integer", min, max, step,
                    slider: min !== undefined && max !== undefined });
    } else if (inner.type === "string") {
      fields.push({ ...f, type: "text" });
    } else if (inner.anyOf) {
      fields.push({ ...f, type: "text", mixed: true });  // ví dụ float | "50%"
    } else if (inner.type === "array" && inner.items && (resolve(root, inner.items).type === "string")) {
      fields.push({ ...f, type: "csv" });
    } else if (inner.type === "object" && inner.properties) {
      if (nullable) {
        fields.push({ ...f, type: "optobj", defaults: defaultsFor(root, inner) });
        fields.push(...buildFields(root, inner, path, opts, depth + 1, path));
      } else {
        fields.push({ ...f, type: "group" });
        fields.push(...buildFields(root, inner, path, opts, depth + 1, showIf));
      }
    } else if (inner.type === "object" || inner.type === "array") {
      fields.push({ ...f, type: "json" });
    }
  }
  return fields;
}
