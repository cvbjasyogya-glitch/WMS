import { Button } from "../button/Button"

interface Props {
    setPage: React.Dispatch<React.SetStateAction<number>>
    totalPages: number
    page: number
}

export const Pagination: React.FC<Props> = ({ page, setPage, totalPages }) => {
    return (
        <>
            <div className="flex justify-between pt-4 items-center border-t">
                <div className="w-[8em]">
                    {totalPages !== 0 && page !== 1 && <Button onClick={() => setPage(page - 1)} label="Prev" className="text-sm" />}
                </div>
                <div className="w-[20em]  text-center text-black/80">
                    Halaman <b className='text-blue-500'>{page}</b> dari <b className='text-blue-500'>{totalPages}</b>
                </div>
                <div className="w-[8em]">
                    {totalPages !== 0 && page !== totalPages && <Button onClick={() => setPage(page + 1)} label="Next" className="text-sm" />}
                </div>
            </div>
        </>
    )
}