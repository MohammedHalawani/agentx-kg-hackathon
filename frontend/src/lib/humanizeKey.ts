// Shared by GraphView's node-detail panel - kept out of a component file so exporting it doesn't
// break Fast Refresh. snake_case DB property names read as raw internals ("municipality_id") -
// strip the _id/_key noise and title-case the rest so the panel reads "Municipality", not a column name.
export const humanizeKey = (key: string): string =>
  key
    .replace(/_(id|key)$/i, '')
    .split('_')
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')
