interface Props {
    message: string
    icon: React.ReactNode
}

export const MasterCallout: React.FC<Props> = ({ ...props }) => {
    const { message, icon: Icon } = props
    return (
        <>
            <div className="bg-slate-100 p-4 rounded-md border">
                <div className="flex items-center gap-x-2">
                    {Icon}
                    <div className="font-bold text-gray-500 text-lg">Info</div>
                </div>
                <div dangerouslySetInnerHTML={{ __html: message }} className="text-gray-500 mt-1" />
            </div>
        </>
    )
}