"""Ask a Question page — Chat interface to the billing intelligence agents."""

import uuid
import streamlit as st
from utils.agentcore_client import ask_billing_question

st.title("Ask a Question")

st.caption(
    "Ask natural language questions about your AWS costs. "
    "Powered by the billing intelligence agents."
)

# Initialize session state FIRST (before any UI that uses it)
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

# Generate a unique session ID per browser tab (persists until tab is closed/refreshed)
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]

# Show session indicator
with st.expander("ℹ️ Session Info", expanded=False):
    st.markdown(f"""
    **Session ID:** `{st.session_state.session_id}`
    
    Your conversation context is preserved for this browser tab. 
    The agent will remember previous questions and answers.
    
    - **Refresh/close tab** → New session (context reset)
    - **Clear conversation** → New session (context reset)
    - **Multiple tabs** → Each tab has its own session
    """)

# Example questions
with st.expander("Example questions you can ask"):
    st.markdown("""
    - Why did our costs go up yesterday?
    - How much are we spending on RDS this month vs last month?
    - Which EC2 instances should we stop?
    - What's our projected spend for this month?
    - Show me a breakdown by team tag
    - What would we save with a 1-year Savings Plan?
    - Compare this week's spend to last week
    - What are our top 5 cost drivers?
    """)

# Display chat history
for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Chat input
if prompt := st.chat_input("Ask about your AWS costs..."):
    # Add user message
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # Get agent response (pass session ID for context persistence)
    with st.chat_message("assistant"):
        with st.spinner("Analyzing your costs..."):
            response = ask_billing_question(prompt, thread_id=st.session_state.session_id)
        st.write(response)

    # Add assistant response
    st.session_state.chat_messages.append({"role": "assistant", "content": response})

# Clear chat button
if st.session_state.chat_messages:
    if st.button("Clear conversation", type="secondary"):
        st.session_state.chat_messages = []
        # Generate new session ID to start fresh conversation (agent memory won't carry over)
        st.session_state.session_id = str(uuid.uuid4())[:8]
        st.rerun()
