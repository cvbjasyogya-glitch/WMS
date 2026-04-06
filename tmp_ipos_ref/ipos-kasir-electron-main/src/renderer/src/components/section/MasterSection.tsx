interface Props {
    text: string
}

export const MasterSection: React.FC<Props> = ({ ...props }) => {
    const { text } = props
    return (
        <>
            <div className="font-semibold text-lg mt-4 py-2 mb-4 border-b ">{text}</div>
        </>
    )
}