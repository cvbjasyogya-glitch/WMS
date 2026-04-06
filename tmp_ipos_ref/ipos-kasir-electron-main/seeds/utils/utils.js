exports.now = function () {
  const nowUtc = new Date()

  const jakartaOffset = 7 * 60 * 60 * 1000
  const jakartaDate = new Date(nowUtc.getTime() + jakartaOffset)

  const year = jakartaDate.getUTCFullYear()
  const month = String(jakartaDate.getUTCMonth() + 1).padStart(2, '0')
  const day = String(jakartaDate.getUTCDate()).padStart(2, '0')
  const hours = String(jakartaDate.getUTCHours()).padStart(2, '0')
  const minutes = String(jakartaDate.getUTCMinutes()).padStart(2, '0')
  const seconds = String(jakartaDate.getUTCSeconds()).padStart(2, '0')
  const milliseconds = String(jakartaDate.getUTCMilliseconds()).padStart(3, '0')

  const formattedDate = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}.${milliseconds}${'+00'}`

  return formattedDate
}
