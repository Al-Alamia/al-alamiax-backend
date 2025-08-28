import { FC, useCallback, useContext, useEffect, useRef, useState } from "react";
import { IoSend } from "react-icons/io5";
import { LanguageContext } from "../../contexts/LanguageContext";
import { TRANSLATIONS } from "../../utils/constants";
import { MdKeyboardDoubleArrowDown } from "react-icons/md";
import { getSocket } from "../../services/socket";

interface WAInputMessageProps {
    targetId: string;
};

export const WAInputMessage: FC<WAInputMessageProps> = ({ targetId }) => {
    const [message, setMessage] = useState("");
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const { lang } = useContext(LanguageContext);
    const handleSubmit = useCallback(() => {
        const socket = getSocket();
        if (!socket || !textareaRef.current?.value.trim()) return;
        socket.emit("sendMessage", {
            to: targetId,
            message: textareaRef.current.value,
        });
        socket.emit("getChatMessages", {
            chatId: targetId,
            limit: 1000,
        });
        setMessage("");
        textareaRef.current.value = "";
    }, [targetId, textareaRef]);

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight - 17}px`;
        }
    }, [message]);

    useEffect(() => {
        window.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                handleSubmit();
            }
        });
        return () => {
            window.removeEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    handleSubmit();
                }
            });
        };
    }, [handleSubmit]);
    return (
        <div className="sticky bottom-0 w-[93%] flex flex-row justify-center items-center gap-3 p-2">
            <textarea 
                dir={lang === "ar" ? "rtl" : "ltr"} 
                ref={textareaRef} 
                value={message} 
                onChange={(e) => setMessage(e.target.value)} 
                placeholder={TRANSLATIONS.WAInputMessage.placeholder[lang]} 
                className="text-start rounded-xl p-2 px-4 w-full resize-none border-[gray] bg-light-colors-login-third-bg dark:border-[#374558] dark:bg-dark-colors-login-third-bg" 
                />
            <button type="submit" disabled={message.trim() === ""} className="bg-[#25d366] rounded-full flex justify-center items-center w-[50px] h-[50px]" onClick={handleSubmit}><IoSend className="w-[20px] h-[20px] text-center"/></button>
            <button type="button" disabled={message.trim() === ""} className="bg-[#25d366] rounded-full flex justify-center items-center w-[40px] h-[40px]"><MdKeyboardDoubleArrowDown className="w-[30px] h-[30px] text-center"/></button>
        </div>
    );
}

export default WAInputMessage;
