// A small picture for each card, from its first recognised cuisine. The dataset has no photos.

const ICONS = [
  [/ice cream|gelato/, "🍨"],
  [/dessert|bakery|mithai|sweet/, "🍰"],
  [/cafe|coffee|tea|beverage|juice/, "☕"],
  [/pizza|italian/, "🍕"],
  [/burger|fast food|american/, "🍔"],
  [/japanese|sushi/, "🍣"],
  [/chinese|asian|momos|tibetan|thai|vietnamese|korean|pan-asian|burmese/, "🥡"],
  [/biryani|hyderabadi|mughlai|north indian|awadhi|kebab|rajasthani|gujarati|bengali|oriya/, "🍛"],
  [/south indian|kerala|andhra|chettinad|mangalorean|maharashtrian|udupi/, "🥘"],
  [/mexican|tex-mex/, "🌮"],
  [/arabian|lebanese|middle eastern|mediterranean|turkish|rolls|shawarma/, "🥙"],
  [/seafood|fish/, "🐟"],
  [/bar food|pub|brewery|drinks/, "🍺"],
  [/healthy|salad/, "🥗"],
  [/continental|european|french|steak|grill|bbq|barbecue/, "🍽️"],
];

/** The icon for a cuisines line such as "Ice Cream, Desserts". */
export function cuisineIcon(cuisines) {
  for (const cuisine of String(cuisines).toLowerCase().split(",")) {
    const match = ICONS.find(([pattern]) => pattern.test(cuisine));
    if (match) return match[1];
  }
  return "🍽️";
}
