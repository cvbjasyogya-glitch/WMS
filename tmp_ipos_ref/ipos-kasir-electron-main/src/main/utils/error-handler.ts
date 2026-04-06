export const handleDatabaseError = (error: string): { success: boolean; error: string } => {
  switch (true) {
    case /UNIQUE constraint failed: \w+\.(\w+)/.test(error):
      const match = error.match(/UNIQUE constraint failed: \w+\.(\w+)/)
      if (match) {
        const fieldName = match[1]
        return {
          success: false,
          error: `Error : Data ${fieldName.split('_')[0]} sudah ada, gunakan ${fieldName.split('_')[0]} lain.`
        }
      }
      break

    // You can add more cases for different error types here
    // case /ANOTHER_ERROR_TYPE/.test(error):
    //   return { success: false, error: 'Custom error message for another error type.' };

    default:
      return { success: false, error }
  }
  return { success: false, error: 'An unexpected error occurred' }
}
