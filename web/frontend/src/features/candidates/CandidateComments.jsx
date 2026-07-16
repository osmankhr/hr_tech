import React, { useEffect, useState } from 'react';
import { candidateApi } from '../../api/candidateApi';
import { Button } from '../../components/ui/Button';

function CommentItem({ comment, allComments, onReply }) {
  const [showReply, setShowReply] = useState(false);
  const [replyText, setReplyText] = useState('');
  
  const replies = allComments.filter(c => c.parent_id === comment.id);
  const dateStr = new Date(comment.created_at).toLocaleString();

  const handleReplySubmit = () => {
    if (!replyText.trim()) return;
    onReply(comment.id, replyText);
    setReplyText('');
    setShowReply(false);
  };

  return (
    <div className="flex flex-col gap-2 mt-4">
      <div className="flex gap-3">
        {/* Avatar Placeholder */}
        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-orange-400 to-orange-600 flex items-center justify-center text-white font-bold text-xs shadow-md shrink-0">
          {comment.user_name ? comment.user_name.charAt(0).toUpperCase() : 'U'}
        </div>
        
        <div className="flex-1 bg-white border border-slate-100 shadow-sm rounded-2xl rounded-tl-none p-3">
          <div className="flex items-baseline gap-2 mb-1">
            <span className="font-semibold text-slate-800 text-sm">{comment.user_name}</span>
            <span className="text-xs text-slate-400">{dateStr}</span>
          </div>
          <p className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">{comment.content}</p>
          
          <button 
            onClick={() => setShowReply(!showReply)}
            className="text-xs text-orange-600 font-medium hover:text-orange-700 mt-2 transition-colors"
          >
            Reply
          </button>
        </div>
      </div>

      {showReply && (
        <div className="ml-11 mt-2 flex gap-2">
          <textarea
            autoFocus
            rows={1}
            className="flex-1 rounded-xl border border-slate-300 p-2 text-sm focus:border-orange-500 focus:ring-1 focus:ring-orange-500 outline-none resize-none transition-all"
            placeholder="Write a reply..."
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
          />
          <Button size="sm" onClick={handleReplySubmit}>Send</Button>
        </div>
      )}

      {/* Nested Replies */}
      {replies.length > 0 && (
        <div className="ml-11 border-l-2 border-slate-100 pl-4">
          {replies.map(reply => (
            <CommentItem key={reply.id} comment={reply} allComments={allComments} onReply={onReply} />
          ))}
        </div>
      )}
    </div>
  );
}

export function CandidateComments({ candidateId }) {
  const [comments, setComments] = useState([]);
  const [newComment, setNewComment] = useState('');
  const [loading, setLoading] = useState(true);

  const fetchComments = () => {
    candidateApi.getComments(candidateId).then(data => {
      setComments(data);
      setLoading(false);
    });
  };

  useEffect(() => {
    if (candidateId) fetchComments();
  }, [candidateId]);

  const handleAddComment = (parentId = null, content) => {
    candidateApi.addComment(candidateId, { content, parent_id: parentId }).then(() => {
      fetchComments();
      if (!parentId) setNewComment('');
    });
  };

  // Only render root comments here; children will be rendered recursively
  const rootComments = comments.filter(c => !c.parent_id);

  if (loading) return <div className="p-4 text-center text-sm text-slate-500">Loading comments...</div>;

  return (
    <div className="flex flex-col h-full space-y-4">
      {/* New Comment Input */}
      <div className="bg-slate-50 p-4 rounded-2xl border border-slate-100 shadow-sm flex flex-col gap-3">
        <textarea
          rows={3}
          className="w-full rounded-xl border border-slate-300 p-3 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-200 outline-none resize-none transition-all"
          placeholder="Add a comment about this candidate..."
          value={newComment}
          onChange={(e) => setNewComment(e.target.value)}
        />
        <div className="flex justify-end">
          <Button onClick={() => handleAddComment(null, newComment)} disabled={!newComment.trim()}>
            Post Comment
          </Button>
        </div>
      </div>

      {/* Comments List */}
      <div className="flex-1 overflow-y-auto pr-2 pb-8">
        {rootComments.length === 0 ? (
          <div className="text-center py-8 text-slate-400 text-sm italic">No comments yet. Be the first to share your thoughts!</div>
        ) : (
          rootComments.map(comment => (
            <CommentItem 
              key={comment.id} 
              comment={comment} 
              allComments={comments} 
              onReply={handleAddComment} 
            />
          ))
        )}
      </div>
    </div>
  );
}
