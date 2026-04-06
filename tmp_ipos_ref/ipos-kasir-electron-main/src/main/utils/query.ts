interface ForeignKey {
  column: string
  referencedTable: string
  referencedColumn: string
  selectColumns?: string[]
  foreignKey?: ForeignKey[]
}

export const insertQuery = (table: string, data: Record<string, any>) => {
  const columns = Object.keys(data)
  const placeholders = columns.map(() => '?').join(', ')
  const query = `INSERT INTO ${table} (${columns.join(', ')}) VALUES (${placeholders})`
  return query
}

export const insertManyQuery = (table: string, data: Array<Record<string, any>>) => {
  if (data.length === 0) {
    throw new Error('No data provided for insertion.')
  }

  const columns = Object.keys(data[0])
  const placeholders = columns.map(() => '?').join(', ')

  const query = `INSERT OR IGNORE INTO ${table} (${columns.join(', ')}) VALUES (${placeholders})`
  return query
}

export const fetchAllQuery = (table: string, foreignKeys: ForeignKey[] = []): string => {
  let query = `SELECT ${table}.*`
  const joinClauses: string[] = []

  if (foreignKeys.length > 0) {
    foreignKeys.forEach((fk) => {
      const columnsToSelect =
        fk.selectColumns && fk.selectColumns.length > 0
          ? fk.selectColumns
              .map((col) => `${fk.referencedTable}.${col} AS ${fk.referencedTable}_${col}`)
              .join(', ')
          : `${fk.referencedTable}.*`

      joinClauses.push(
        `LEFT JOIN ${fk.referencedTable} ON ${table}.${fk.column} = ${fk.referencedTable}.${fk.referencedColumn}`
      )
      query += `, ${columnsToSelect}`
    })
  }

  query += ` FROM ${table} ${joinClauses.join(' ')}`
  return query
}

export const fetchByIdQuery = (table: string, id: any) => {
  const query = `SELECT * FROM ${table} WHERE id = ${id}`
  return query
}

export const fetchByFieldQuery = (table: string, field: string, foreignKeys: ForeignKey[] = []) => {
  let query = `SELECT ${table}.*`
  const joinClauses: string[] = []

  if (foreignKeys.length > 0) {
    foreignKeys.forEach((fk) => {
      const columnsToSelect =
        fk.selectColumns && fk.selectColumns.length > 0
          ? fk.selectColumns
              .map((col) => `${fk.referencedTable}.${col} AS ${fk.referencedTable}_${col}`)
              .join(', ')
          : `${fk.referencedTable}.*`

      joinClauses.push(
        `LEFT JOIN ${fk.referencedTable} ON ${table}.${fk.column} = ${fk.referencedTable}.${fk.referencedColumn}`
      )
      query += `, ${columnsToSelect}`
    })
  }

  query += ` FROM ${table} ${joinClauses.join(' ')} WHERE ${field} = ?`
  return query
}

export const fetchByFieldsQuery = (
  table: string,
  fields: string[],
  foreignKeys: ForeignKey[] = []
) => {
  let query = `SELECT ${table}.*`
  const joinClauses: string[] = []

  if (foreignKeys.length > 0) {
    foreignKeys.forEach((fk) => {
      const columnsToSelect =
        fk.selectColumns && fk.selectColumns.length > 0
          ? fk.selectColumns
              .map((col) => `${fk.referencedTable}.${col} AS ${fk.referencedTable}_${col}`)
              .join(', ')
          : `${fk.referencedTable}.*`

      joinClauses.push(
        `LEFT JOIN ${fk.referencedTable} ON ${table}.${fk.column} = ${fk.referencedTable}.${fk.referencedColumn}`
      )
      query += `, ${columnsToSelect}`
    })
  }

  // Construct the WHERE clause for multiple fields
  if (fields.length > 0) {
    const whereClauses = fields.map((field) => `${field} = ?`).join(' AND ')
    query += ` FROM ${table} ${joinClauses.join(' ')} WHERE ${whereClauses}`
  } else {
    query += ` FROM ${table} ${joinClauses.join(' ')}`
  }

  return query
}
export const countQuery = (
  table: string,
  id?: number,
  field?: string,
  timeField?: string,
  start?: string,
  end?: string
) => {
  let query = `SELECT COUNT(*) as count FROM ${table}`
  const whereClauses: string[] = []

  if (start === undefined && end === undefined) {
    return query
  }

  if (id !== undefined && id !== -1 && field) {
    whereClauses.push(`${table}.${field} = ?`)
  }

  if (start && start !== '' && end && end !== '') {
    whereClauses.push(`DATE(${table}.${timeField}) BETWEEN ? AND ?`)
  } else if (start && start !== '') {
    whereClauses.push(`DATE(${table}.${timeField}) = ?`)
  } else if (end && end !== '') {
    whereClauses.push(`DATE(${table}.${timeField}) = ?`)
  }

  if (whereClauses.length > 0) {
    query += ` WHERE ${whereClauses.join(' AND ')}`
  }

  return query
}

export const fetchLimitQuery = (
  table: string,
  foreignKeys: ForeignKey[] = [],
  id?: number,
  field?: string,
  timeField?: string,
  start?: string,
  end?: string
): string => {
  let query = `SELECT ${table}.*`
  const joinClauses: string[] = []
  const whereClauses: string[] = []

  // Recursive function to handle nested foreign keys
  const processForeignKeys = (fkList: ForeignKey[], parentTable: string) => {
    fkList.forEach((fk) => {
      const columnsToSelect =
        fk.selectColumns && fk.selectColumns.length > 0
          ? fk.selectColumns
              .map((col) => `${fk.referencedTable}.${col} AS ${fk.referencedTable}_${col}`)
              .join(', ')
          : `${fk.referencedTable}.*`

      joinClauses.push(
        `LEFT JOIN ${fk.referencedTable} ON ${parentTable}.${fk.column} = ${fk.referencedTable}.${fk.referencedColumn}`
      )
      query += `, ${columnsToSelect}`

      // Simplified nested foreign key handling
      if (fk.foreignKey?.length) {
        processForeignKeys(fk.foreignKey, fk.referencedTable)
      }
    })
  }

  // Start processing foreign keys for the base table
  if (foreignKeys.length > 0) {
    processForeignKeys(foreignKeys, table)
  }

  query += ` FROM ${table} ${joinClauses.join(' ')}`

  // WHERE conditions
  if (id && id !== -1 && field && field !== null) {
    whereClauses.push(`${table}.${field} = ?`)
  }

  if (start && start !== '' && end && end !== '') {
    whereClauses.push(`DATE(${table}.${timeField}) BETWEEN ? AND ?`)
  } else if (start && start !== '') {
    whereClauses.push(`DATE(${table}.${timeField}) = ?`)
  } else if (end && end !== '') {
    whereClauses.push(`DATE(${table}.${timeField}) = ?`)
  }

  if (whereClauses.length > 0) {
    query += ` WHERE ${whereClauses.join(' AND ')}`
  }
  query += ` ORDER BY ${table}.id DESC`
  query += ` LIMIT ? OFFSET ?`

  return query
}

export const searchQuery = (table: string, fields: string[]) => {
  const conditions = fields.map((field) => `${field} LIKE $1`).join(' OR ')
  const query = `SELECT * FROM ${table} WHERE ${conditions}`
  return query
}

export const queryFilterTimestamp = (
  table: string,
  field: string,
  start: string,
  end: string,
  foreignKeys: ForeignKey[] = []
): string => {
  let query = `SELECT ${table}.*`
  const joinClauses: string[] = []

  if (foreignKeys.length > 0) {
    foreignKeys.forEach((fk) => {
      const columnsToSelect =
        fk.selectColumns && fk.selectColumns.length > 0
          ? fk.selectColumns
              .map((col) => `${fk.referencedTable}.${col} AS ${fk.referencedTable}_${col}`)
              .join(', ')
          : `${fk.referencedTable}.*`

      joinClauses.push(
        `LEFT JOIN ${fk.referencedTable} ON ${table}.${fk.column} = ${fk.referencedTable}.${fk.referencedColumn}`
      )
      query += `, ${columnsToSelect}`
    })
  }

  query += ` FROM ${table} ${joinClauses.join(' ')}`

  if (start === '' || end === '') {
    query += ` WHERE DATE(${field}) = ?`
  } else {
    query += ` WHERE ${field} BETWEEN ? AND ?`
  }

  return query
}

export const updateQuery = (table: string, payload: any) => {
  const setClause = Object.keys(payload)
    .map((field) => `${field} = ?`)
    .join(', ')
  const query = `UPDATE ${table} SET ${setClause}, updated_at = datetime(CURRENT_TIMESTAMP, '+7 hours') WHERE id = ?`
  return query
}

export const updateManyQuery = (table: string, paramId: string[], payload: Array<any>) => {
  const setClauses = Object.keys(payload[0])
    .filter((key) => key !== 'id' && key !== 'product_id' && key !== 'unit_id')
    .map((key) => {
      return (
        `${key} = CASE ` +
        `WHEN ${paramId.length > 1 ? paramId.map((field) => `${field} = ?`).join(' AND ') : `${paramId} = ? `} THEN ${key == 'stock' ? `${key} + ` : ``}? ` +
        `ELSE ${key} END`
      )
    })
    .join(', ')

  const query = `UPDATE ${table} SET ${setClauses}, updated_at = datetime(CURRENT_TIMESTAMP, '+7 hours')`
  return query
}
export const deleteQuery = (table: string) => {
  const query = `DELETE FROM ${table} WHERE id = ?`
  return query
}
