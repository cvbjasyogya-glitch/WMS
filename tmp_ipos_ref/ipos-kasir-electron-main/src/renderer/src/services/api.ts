export const handleDelete = async (
  id: number,
  section: string,
  setData: React.Dispatch<React.SetStateAction<any[]>>
) => {
  try {
    const response = await (window as any).api[section].delete(id)
    if (response.success) {
      setData((prevData) => prevData.filter((item) => item.id !== id))
      return response
    }
  } catch (error) {
    console.log('Error deleting data: ' + error)
  }
}

export const handleUpdate = async (section: string, id: number, field: string, value: any) => {
  const payload = {
    [field]: field === 'name' ? String(value).toUpperCase() : value
  }

  try {
    const response = await (window.api as any)[section].put(id, payload)
    return response
  } catch (error) {
    throw error
  }
}

export const getDatasByField = async (
  id: number,
  table: string,
  field: string,
  setDatas?: React.Dispatch<React.SetStateAction<any[]>> | null
) => {
  try {
    const response = await (window.api as any)[table].getByField(field, id)
    setDatas && setDatas(response.data)
    return response
  } catch (error) {
    console.log(error)
  }
}
