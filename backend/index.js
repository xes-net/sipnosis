require('dotenv').config();
const express = require('express');
const cors = require('cors');
const { createClient } = require('@supabase/supabase-js');
const OpenAI = require('openai');

const app = express();
app.use(cors());
app.use(express.json());

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE;
const supabase = createClient(supabaseUrl, supabaseKey);

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

function hourKey(date = new Date()) {
  return date.toISOString().slice(0, 13);
}

app.get('/ping', (req, res) => {
  res.json({ ok: true });
});

app.get('/api/question', async (req, res) => {
  const key = hourKey();
  let { data: question, error } = await supabase
    .from('questions')
    .select('*')
    .eq('hour_key', key)
    .single();

  if (error && error.code === 'PGRST116') {
    const insert = await supabase
      .from('questions')
      .insert({ hour_key: key, text: 'What should we discuss?' })
      .select()
      .single();
    question = insert.data;
    error = insert.error;
  }

  if (error) return res.status(500).json({ error: error.message });
  res.json(question);
});

app.post('/api/question', async (req, res) => {
  const key = hourKey();
  const text = req.body.text;
  const { data, error } = await supabase
    .from('questions')
    .upsert({ hour_key: key, text }, { onConflict: 'hour_key' })
    .select()
    .single();
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

app.post('/api/answer', async (req, res) => {
  const { question_id, stance, body, risk } = req.body;
  try {
    const moderation = await openai.moderations.create({
      model: 'omni-moderation-latest',
      input: body,
    });
    const flagged = moderation.results?.[0]?.flagged;
    if (flagged) return res.status(400).json({ error: 'Rejected by moderation' });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }

  const { data, error } = await supabase
    .from('answers')
    .insert({ question_id, stance, body, risk })
    .select()
    .single();
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

app.get('/api/answers', async (req, res) => {
  const key = hourKey();
  const { data: question } = await supabase
    .from('questions')
    .select('id')
    .eq('hour_key', key)
    .single();
  if (!question) return res.json([]);
  const { data, error } = await supabase
    .from('answers')
    .select('*')
    .eq('question_id', question.id)
    .order('created_at', { ascending: false });
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`Server running on port ${port}`);
});
