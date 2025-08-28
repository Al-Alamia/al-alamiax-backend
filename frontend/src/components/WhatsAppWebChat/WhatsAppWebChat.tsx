import { FC, useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import Container from "../../layouts/Container/Container";
import WAInputMessage from "../WAInputMessage/WAInputMessage";
import WAChatMessage from "../WAChatMessage/WAChatMessage";
import { convertJidToPhone } from "../../utils/converter";
import { getSocket } from "../../services/socket";
import { AppChat } from "../../features/chats/chatSlice";
import { RootState } from "../../store/store";
import { AppMessage } from "../../types/whatsapp";

interface WhatsAppWebChatProps {
    refresh: boolean;
    currentChat: AppChat | null;
};

export const WhatsAppWebChat: FC<WhatsAppWebChatProps> = ({ currentChat }) => {
    const dispatch = useDispatch();
    const chats = useSelector((state: RootState) => state.chats.chats);
    const messages = useSelector((state: RootState) => state.messages.messages);
    const selectedChat = chats.find(c => c.id._serialized === currentChat?.id._serialized);

    useEffect(() => {
        const socket = getSocket();
        if (!socket || !currentChat) {
            return;
        }

        // Mark chat as read when opened
        if (currentChat.unreadCount > 0) {
            socket.emit('markChatAsRead', { chatId: currentChat.id._serialized });
        }

        // // Load messages for the chat
        // socket.emit("getChatMessages", {
        //     chatId: currentChat.id._serialized,
        //     limit: 1000,
        // });
    }, [currentChat, dispatch]);

    return (
        <Container className="w-[76%] h-[77vh] bg-wa-colors-background">
            {
                currentChat && selectedChat ? (
                    <>
                        <div className="sticky top-0 flex flex-row justify-between items-center border-b w-full pb-1 text-center bg-wa-colors-background">
                            <label className="w-full text-lg font-bold" htmlFor="">{currentChat?.name} {currentChat?.name ? " | " : ""} {convertJidToPhone(currentChat?.id.user || "")}</label>
                        </div>
                        <div className="flex flex-col overflow-y-auto gap-1 p-2 min-h-[68vh]">
                            {
                                messages?.map((message: AppMessage, index) => {
                                    return <WAChatMessage key={index} message={message} />
                                })
                            }
                        </div>
                        <WAInputMessage targetId={currentChat?.id._serialized || ""} />
                    </>
                ) : (
                    <div className="flex flex-col overflow-y-auto gap-1 p-2 min-h-[68vh]">
                        <label className="w-full text-lg font-bold text-center" htmlFor="">Select a chat</label>
                    </div>
                )
            }
        </Container>
    );
}



export default WhatsAppWebChat;
